import base64
import html as html_lib
import os
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Optional

import pandas as pd
import requests
import yfinance as yf
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.staticfiles import StaticFiles
from playwright.sync_api import Browser, BrowserContext, Page, TimeoutError as PlaywrightTimeoutError, sync_playwright
from pydantic import BaseModel, Field

APP_VERSION = "1.6.0-source-url-encoding-fix"
SCREENSHOT_DIR = Path(os.getenv("SCREENSHOT_DIR", "/tmp/bist_chart_screenshots"))
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
CACHE_TTL_SECONDS = int(os.getenv("OHLC_CACHE_TTL_SECONDS", "300"))
QUOTE_CACHE_TTL_SECONDS = int(os.getenv("QUOTE_CACHE_TTL_SECONDS", "120"))
TRADINGVIEW_COOKIE = os.getenv("TRADINGVIEW_COOKIE", "").strip()

TV_INTERVALS = {"1m": "1", "3m": "3", "5m": "5", "10m": "10", "15m": "15", "30m": "30", "1h": "60", "1d": "D"}
YF_INTERVALS = {"1m": "1m", "3m": "5m", "5m": "5m", "10m": "15m", "15m": "15m", "30m": "30m", "1h": "60m", "1d": "1d"}
YF_ALLOWED_PERIODS = {"1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "10y", "ytd", "max"}

BLOOMBERGHT_SLUGS = {
    "THYAO": "thyao-turk-hava-yollari-detay",
    "TUPRS": "tuprs-tupras-detay",
    "ASELS": "asels-aselsan-detay",
    "AKBNK": "akbnk-akbank-detay",
    "TCELL": "tcell-turkcell-detay",
    "TAVHL": "tavhl-tav-havalimanlari-detay",
    "HLGYO": "hlgyo-halk-gmyo-detay",
    "SELVA": "selva-selva-gida-detay",
    "A1YEN": "a1yen-a1-yenilenebilir-enerji-detay",
}

INVESTING_SLUGS = {
    "THYAO": "turk-hava-yollari",
    "TUPRS": "tupras",
    "ASELS": "aselsan",
    "AKBNK": "akbank",
    "TCELL": "turkcell",
    "TAVHL": "tav-havalimanlari",
}


OHLC_CACHE: dict[str, tuple[float, list[dict], str, str, str]] = {}
QUOTE_CACHE: dict[str, tuple[float, list[dict], dict]] = {}

class BrowserManager:
    def __init__(self):
        self._lock = Lock()
        self._pw = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self.started_at = None

    def get_context(self) -> BrowserContext:
        with self._lock:
            if self._context:
                return self._context
            self._pw = sync_playwright().start()
            self._browser = self._pw.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu", "--disable-features=IsolateOrigins,site-per-process"],
            )
            extra_headers = {}
            if TRADINGVIEW_COOKIE:
                extra_headers["Cookie"] = TRADINGVIEW_COOKIE
            self._context = self._browser.new_context(
                viewport={"width": 1440, "height": 950},
                device_scale_factor=1,
                locale="tr-TR",
                timezone_id="Europe/Istanbul",
                extra_http_headers=extra_headers,
                user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36",
            )
            self.started_at = datetime.now(timezone.utc).isoformat()
            return self._context

    def reset(self):
        with self._lock:
            try:
                if self._context:
                    self._context.close()
            except Exception:
                pass
            try:
                if self._browser:
                    self._browser.close()
            except Exception:
                pass
            try:
                if self._pw:
                    self._pw.stop()
            except Exception:
                pass
            self._pw = None
            self._browser = None
            self._context = None
            self.started_at = None

BROWSER = BrowserManager()

class ChartResponse(BaseModel):
    symbol: str
    yahoo_symbol: str
    interval: str
    yahoo_interval_used: str
    range_hint: str
    target_date: Optional[str] = None
    source_chart: str
    source_data: str
    tradingview_url: str
    screenshot_url: Optional[str] = None
    screenshot_base64_png: Optional[str] = Field(default=None, description="include_base64=true ise gelir; aksi halde null döner.")
    chart_status: str
    ohlc_sample: list[dict]
    ohlc_count: int
    quote_snapshots: list[dict] = Field(default_factory=list)
    official_reference: dict = Field(default_factory=dict)
    data_status: str
    data_note: str
    captured_at_utc: str

app = FastAPI(
    title="BIST Chart GPT Action API",
    description="ChatGPT Actions uyumlu BIST grafik servisi: TradingView screenshot + Yahoo/Stooq/Midas/BloombergHT/Investing/Borsa İstanbul doğrulama katmanları.",
    version=APP_VERSION,
)
app.mount("/screenshots", StaticFiles(directory=str(SCREENSHOT_DIR)), name="screenshots")

@app.on_event("shutdown")
def shutdown_event():
    BROWSER.reset()

@app.get("/")
def root():
    return {"ok": True, "service": "bist-chart-gpt-action", "version": APP_VERSION, "endpoints": ["/health", "/warmup", "/chart"]}

@app.get("/health")
def health():
    return {"ok": True, "service": "bist-chart-gpt-action", "version": APP_VERSION, "browser_started_at": BROWSER.started_at}

@app.get("/warmup")
def warmup():
    try:
        ctx = BROWSER.get_context()
        page = ctx.new_page()
        page.goto("https://tr.tradingview.com/chart/", wait_until="domcontentloaded", timeout=90000)
        page.wait_for_timeout(5000)
        page.close()
        return {"ok": True, "version": APP_VERSION, "browser_started_at": BROWSER.started_at}
    except Exception as e:
        BROWSER.reset()
        raise HTTPException(status_code=503, detail=f"Warmup başarısız: {type(e).__name__}: {e}")

def normalize_symbol(symbol: str) -> str:
    s = symbol.upper().replace(".IS", "").replace("BIST:", "").strip()
    s = re.sub(r"[^A-Z0-9]", "", s)
    if not s:
        raise HTTPException(status_code=400, detail="Sembol boş olamaz. Örn: THYAO, ASELS, TUPRS")
    if len(s) > 12:
        raise HTTPException(status_code=400, detail="Sembol çok uzun görünüyor. Örn: THYAO, ASELS, TUPRS")
    return s

def make_yahoo_symbol(symbol: str) -> str:
    return f"{normalize_symbol(symbol)}.IS"

def make_tv_url(symbol: str, interval: str) -> str:
    return f"https://tr.tradingview.com/chart/?symbol=BIST:{symbol}&interval={TV_INTERVALS.get(interval, '5')}"

def absolute_url(request: Request, path: str) -> str:
    return f"{str(request.base_url).rstrip('/')}{path}"

def click_soft_popups(page: Page):
    selectors = [
        "button[aria-label='Close']", "button[aria-label='Kapat']", "button[data-name='close']",
        "button:has-text('Accept')", "button:has-text('Kabul')", "button:has-text('Tümünü kabul et')",
        "button:has-text('I understand')", "button:has-text('Anladım')", "button:has-text('Later')",
    ]
    for selector in selectors:
        try:
            page.locator(selector).first.click(timeout=600)
            page.wait_for_timeout(250)
        except Exception:
            pass

def screenshot_tradingview(url: str, symbol: str, interval: str) -> tuple[Optional[Path], Optional[str], str, str]:
    filename = f"{symbol}_{interval}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{uuid.uuid4().hex[:8]}.png"
    out_path = SCREENSHOT_DIR / filename
    chart_status = "ok"
    chart_note = "TradingView grafiği yüklendi ve screenshot alındı."
    ctx = BROWSER.get_context()
    page = None
    try:
        page = ctx.new_page()
        page.set_default_timeout(18000)
        page.set_default_navigation_timeout(90000)
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=90000)
        except PlaywrightTimeoutError:
            chart_status = "partial_timeout"
            chart_note = "TradingView domcontentloaded timeout verdi; eldeki sayfa screenshotlandı."
        page.wait_for_timeout(int(os.getenv("TV_INITIAL_WAIT_MS", "14000")))
        click_soft_popups(page)
        canvas_found = False
        for selector in ["canvas", "div.chart-container", "div[data-name='legend-source-item']"]:
            try:
                page.locator(selector).first.wait_for(state="visible", timeout=10000)
                canvas_found = True
                break
            except Exception:
                pass
        if not canvas_found and chart_status == "ok":
            chart_status = "partial_no_canvas_detected"
            chart_note = "TradingView açıldı ama canvas/legend doğrulanamadı; viewport screenshot alındı."
        page.screenshot(path=str(out_path), full_page=False, type="png")
        return out_path, f"/screenshots/{filename}", chart_status, chart_note
    except Exception as e:
        chart_status = "chart_failed_data_only"
        chart_note = f"TradingView screenshot başarısız; veri katmanları yine döndürüldü. Hata: {type(e).__name__}: {e}"
        try:
            if page:
                page.screenshot(path=str(out_path), full_page=False, type="png")
                return out_path, f"/screenshots/{filename}", "partial_screenshot_recovered", chart_note
        except Exception:
            pass
        BROWSER.reset()
        return None, None, chart_status, chart_note
    finally:
        try:
            if page:
                page.close()
        except Exception:
            pass

def df_to_records(df: pd.DataFrame, limit: int = 80) -> list[dict]:
    if df is None or df.empty:
        return []
    out = df.tail(limit).reset_index()
    records = []
    for _, row in out.iterrows():
        rec = {}
        for k, v in row.items():
            key = str(k).lower().replace(" ", "_")
            if hasattr(v, "isoformat"):
                rec[key] = v.isoformat()
            elif pd.isna(v):
                rec[key] = None
            elif isinstance(v, (int, float)):
                rec[key] = round(float(v), 4)
            else:
                rec[key] = str(v)
        records.append(rec)
    return records

def fetch_yahoo_ohlc(yahoo_symbol: str, interval: str, range_hint: str, target_date: Optional[str]) -> tuple[list[dict], str, str]:
    yf_interval = YF_INTERVALS.get(interval, "5m")
    period = range_hint if range_hint in YF_ALLOWED_PERIODS else "5d"
    if target_date:
        period = "3mo" if yf_interval != "1d" else "1y"
    cache_key = f"yahoo:{yahoo_symbol}:{yf_interval}:{period}:{target_date or ''}"
    cached = OHLC_CACHE.get(cache_key)
    if cached and time.time() - cached[0] < CACHE_TTL_SECONDS:
        return cached[1], "cache_yahoo", cached[4]
    try:
        df = yf.download(yahoo_symbol, period=period, interval=yf_interval, progress=False, auto_adjust=False, threads=False)
        records = df_to_records(df, 120)
        status = "ok_yahoo_intraday" if records and yf_interval != "1d" else ("ok_yahoo_daily" if records else "no_yahoo_data")
        note = f"Yahoo Finance {yahoo_symbol} interval={yf_interval} period={period}."
        OHLC_CACHE[cache_key] = (time.time(), records, status, "Yahoo Finance", note)
        return records, status, note
    except Exception as e:
        note = f"Yahoo Finance hata: {type(e).__name__}: {e}"
        OHLC_CACHE[cache_key] = (time.time(), [], "yahoo_error", "Yahoo Finance", note)
        return [], "yahoo_error", note

def fetch_stooq_daily(symbol: str) -> tuple[list[dict], str, str]:
    cache_key = f"stooq:{symbol}"
    cached = OHLC_CACHE.get(cache_key)
    if cached and time.time() - cached[0] < CACHE_TTL_SECONDS:
        return cached[1], "cache_stooq_daily", cached[4]
    urls = [
        f"https://stooq.com/q/d/l/?s={symbol.lower()}.tr&i=d",
        f"https://stooq.com/q/d/l/?s={symbol.lower()}.is&i=d",
    ]
    last_error = ""
    for url in urls:
        try:
            r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
            r.raise_for_status()
            if "Date," not in r.text:
                last_error = "CSV beklenen formatta değil"
                continue
            from io import StringIO
            df = pd.read_csv(StringIO(r.text))
            records = df_to_records(df, 80)
            if records:
                note = f"Stooq günlük fallback kullanıldı: {url}"
                OHLC_CACHE[cache_key] = (time.time(), records, "stooq_daily_fallback", "Stooq", note)
                return records, "stooq_daily_fallback", note
        except Exception as e:
            last_error = f"{type(e).__name__}: {e}"
    note = f"Stooq günlük fallback veri bulamadı. Son hata: {last_error}"
    OHLC_CACHE[cache_key] = (time.time(), [], "no_stooq_data", "Stooq", note)
    return [], "no_stooq_data", note

def http_get_text(url: str, timeout: int = 12) -> tuple[str, Optional[str]]:
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/122 Safari/537.36",
        "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    try:
        r = requests.get(url, headers=headers, timeout=timeout)
        r.raise_for_status()
        # Some Turkish pages omit/lie about encoding; apparent_encoding prevents mojibake like ÄŸ/ÅŸ.
        if r.encoding is None or r.encoding.lower() in {"iso-8859-1", "latin-1"}:
            r.encoding = r.apparent_encoding or "utf-8"
        return r.text, None
    except Exception as e:
        return "", f"{type(e).__name__}: {e}"

def clean_html_text(html: str) -> list[str]:
    text = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.I)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "\n", text)
    text = html_lib.unescape(text)
    lines = [re.sub(r"\s+", " ", x).strip() for x in text.splitlines()]
    return [x for x in lines if x]

def extract_context_text(html: str, symbol: str) -> str:
    lines = clean_html_text(html)
    hits = [x for x in lines if symbol.upper() in x.upper() or "BIST" in x.upper() or "ALIŞ" in x.upper() or "SATIŞ" in x.upper() or "HACİM" in x.upper()]
    joined = " | ".join(hits[:28])
    return joined[:1600]

def make_quote_sources(symbol: str) -> list[tuple[str, str]]:
    midas_symbol = symbol.lower()
    sources = [
        ("Midas direct", f"https://www.getmidas.com/canli-borsa/{midas_symbol}-hisse/"),
        ("Midas live table", "https://www.getmidas.com/canli-borsa/"),
    ]
    bloom_slug = BLOOMBERGHT_SLUGS.get(symbol.upper())
    if bloom_slug:
        sources.append(("BloombergHT direct", f"https://www.bloomberght.com/borsa/hisse/{bloom_slug}"))
    sources.append(("BloombergHT borsa", "https://www.bloomberght.com/borsa"))
    inv_slug = INVESTING_SLUGS.get(symbol.upper())
    if inv_slug:
        sources.append(("Investing direct", f"https://tr.investing.com/equities/{inv_slug}"))
    sources.append(("Investing search", f"https://tr.investing.com/search/?q={symbol}"))
    return sources

def fetch_public_quotes(symbol: str) -> tuple[list[dict], dict]:
    cache_key = f"quotes:{symbol}"
    cached = QUOTE_CACHE.get(cache_key)
    if cached and time.time() - cached[0] < QUOTE_CACHE_TTL_SECONDS:
        return cached[1], cached[2]
    snapshots = []
    for name, url in make_quote_sources(symbol):
        html, err = http_get_text(url)
        entry = {"source": name, "url": url, "status": "ok" if html else "error", "note": None, "context": None}
        if err:
            entry["note"] = err
        else:
            entry["context"] = extract_context_text(html, symbol)
            if name.startswith("Midas"):
                entry["note"] = "Midas canlı borsa sayfası BIST kaynaklı en az 15 dakika gecikmeli olabilir; ek fiyat teyidi olarak kullanılır."
            if name.startswith("BloombergHT"):
                entry["note"] = "BloombergHT sayfası fiyat/yüzde/hacim teyidi için ek kaynak olarak kullanılır."
            if name.startswith("Investing"):
                entry["note"] = "Investing sayfası fiyat/yüzde ve haber bağlamı için ek kaynak olarak kullanılır."
        snapshots.append(entry)
    official = {
        "source": "Borsa Istanbul",
        "status": "reference_only",
        "url": "https://www.borsaistanbul.com/",
        "note": "Resmi kaynak/duyuru/günlük bülten referansı. Ücretsiz canlı 1dk/5dk mum API kaynağı gibi kullanılmaz.",
    }
    QUOTE_CACHE[cache_key] = (time.time(), snapshots, official)
    return snapshots, official

def build_ohlc(symbol: str, yahoo_symbol: str, interval: str, range_hint: str, target_date: Optional[str]):
    records, status, note = fetch_yahoo_ohlc(yahoo_symbol, interval, range_hint, target_date)
    if records:
        return records, status, note
    stooq_records, stooq_status, stooq_note = fetch_stooq_daily(symbol)
    combined_note = f"{note} | {stooq_note}"
    if stooq_records:
        return stooq_records, stooq_status, combined_note
    return [], "no_ohlc_all_sources", combined_note

@app.get("/chart", response_model=ChartResponse)
def chart(
    request: Request,
    symbol: str = Query(..., description="BIST sembolü. Örn: THYAO, ASELS, TUPRS"),
    interval: str = Query("5m", description="1m, 3m, 5m, 10m, 15m, 30m, 1h, 1d"),
    range_hint: str = Query("5d", description="Yahoo period ipucu: 1d, 5d, 1mo, 3mo, 6mo, 1y..."),
    target_date: Optional[str] = Query(None, description="YYYY-MM-DD; tarihli analiz için doğrulama notu/veri aralığı."),
    include_base64: bool = Query(False, description="true ise screenshot base64 döner; genelde false kalsın."),
):
    clean_symbol = normalize_symbol(symbol)
    if interval not in TV_INTERVALS:
        raise HTTPException(status_code=400, detail=f"Geçersiz interval: {interval}. Destek: {', '.join(TV_INTERVALS.keys())}")
    if target_date and not re.match(r"^\d{4}-\d{2}-\d{2}$", target_date):
        raise HTTPException(status_code=400, detail="target_date YYYY-MM-DD formatında olmalı.")
    yahoo_symbol = make_yahoo_symbol(clean_symbol)
    tv_url = make_tv_url(clean_symbol, interval)

    out_path, shot_path, chart_status, chart_note = screenshot_tradingview(tv_url, clean_symbol, interval)
    records, data_status, data_note = build_ohlc(clean_symbol, yahoo_symbol, interval, range_hint, target_date)
    quote_snapshots, official_reference = fetch_public_quotes(clean_symbol)

    screenshot_base64 = None
    screenshot_url = absolute_url(request, shot_path) if shot_path else None
    if include_base64 and out_path and out_path.exists():
        screenshot_base64 = base64.b64encode(out_path.read_bytes()).decode("utf-8")

    final_note = (
        f"{chart_note} | {data_note} | Ücretsiz kaynaklarda BIST intraday verileri gecikmeli/sınırlı/eksik olabilir. "
        "Mikro yapı, derinlik, AKD/BOFA ve karanlık oda için aracı kurum ekranı gerekir. "
        "GPT analizi önce screenshot'ı, sonra OHLC ve public quote teyitlerini birlikte değerlendirmelidir."
    )

    return ChartResponse(
        symbol=clean_symbol,
        yahoo_symbol=yahoo_symbol,
        interval=interval,
        yahoo_interval_used=YF_INTERVALS.get(interval, "5m"),
        range_hint=range_hint,
        target_date=target_date,
        source_chart="TradingView visual chart screenshot via persistent Playwright browser",
        source_data="Yahoo Finance OHLC + Stooq daily fallback + Midas/BloombergHT/Investing public quote checks + Borsa İstanbul official reference",
        tradingview_url=tv_url,
        screenshot_url=screenshot_url,
        screenshot_base64_png=screenshot_base64,
        chart_status=chart_status,
        ohlc_sample=records,
        ohlc_count=len(records),
        quote_snapshots=quote_snapshots,
        official_reference=official_reference,
        data_status=data_status if records else ("public_quote_fallback" if quote_snapshots else data_status),
        data_note=final_note,
        captured_at_utc=datetime.now(timezone.utc).isoformat(),
    )
