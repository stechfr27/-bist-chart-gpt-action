import base64
import os
import re
import time
import uuid
import requests
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal, Optional

import pandas as pd
import yfinance as yf
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.staticfiles import StaticFiles
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError, sync_playwright
from pydantic import BaseModel, Field

APP_VERSION = "1.3.0-public-source-fallbacks"
SCREENSHOT_DIR = Path(os.getenv("SCREENSHOT_DIR", "/tmp/bist_chart_screenshots"))
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

OHLC_CACHE: dict[str, tuple[float, list[dict], str, str, str]] = {}
CACHE_TTL_SECONDS = int(os.getenv("OHLC_CACHE_TTL_SECONDS", "300"))

app = FastAPI(
    title="BIST Chart GPT Action API",
    description="TradingView mum grafik ekran görüntüsü + Yahoo Finance/Stooq + Midas/Investing/BloombergHT/Borsa İstanbul doğrulama katmanlı servis.",
    version=APP_VERSION,
)
app.mount("/screenshots", StaticFiles(directory=str(SCREENSHOT_DIR)), name="screenshots")

TV_INTERVALS = {
    "1m": "1",
    "3m": "3",
    "5m": "5",
    "10m": "10",
    "15m": "15",
    "30m": "30",
    "1h": "60",
    "1d": "D",
}

YF_INTERVALS = {
    "1m": "1m",
    "3m": "5m",     # Yahoo 3m desteklemez; en yakın güvenli doğrulama 5m.
    "5m": "5m",
    "10m": "15m",   # Yahoo 10m desteklemez; en yakın güvenli doğrulama 15m.
    "15m": "15m",
    "30m": "30m",
    "1h": "60m",
    "1d": "1d",
}

YF_ALLOWED_PERIODS = {"1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "10y", "ytd", "max"}


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
    screenshot_url: str
    screenshot_base64_png: Optional[str] = Field(default=None, description="include_base64=true ise gelir; aksi halde cevap şişmesin diye null döner.")
    ohlc_sample: list[dict]
    ohlc_count: int
    quote_snapshots: list[dict] = Field(default_factory=list, description="Midas/Investing/BloombergHT gibi ücretsiz web kaynaklarından çekilen anlık/özet fiyat teyitleri.")
    official_reference: dict = Field(default_factory=dict, description="Borsa İstanbul resmi site referans/erişim durumu; intraday mum verisi yerine resmi kaynak bağlantısı/teyit notu.")
    data_status: str
    data_note: str
    captured_at_utc: str


@app.get("/health")
def health():
    return {"ok": True, "service": "bist-chart-gpt-action", "version": APP_VERSION}


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
    tv_interval = TV_INTERVALS.get(interval, "5")
    return f"https://tr.tradingview.com/chart/?symbol=BIST:{symbol}&interval={tv_interval}"


def absolute_url(request: Request, path: str) -> str:
    base = str(request.base_url).rstrip("/")
    return f"{base}{path}"


def screenshot_tradingview(url: str, symbol: str, interval: str) -> tuple[Path, str]:
    filename = f"{symbol}_{interval}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{uuid.uuid4().hex[:8]}.png"
    out_path = SCREENSHOT_DIR / filename

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        page = browser.new_page(viewport={"width": 1440, "height": 950}, device_scale_factor=1)
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(8000)

            # Olası pop-up/çerez/uyarı kapatmaları. Bulunmazsa sessiz geçer.
            possible_close_selectors = [
                "button[aria-label='Close']",
                "button[aria-label='Kapat']",
                "button[data-name='close']",
                "button:has-text('Accept')",
                "button:has-text('Kabul')",
                "button:has-text('Tümünü kabul et')",
            ]
            for selector in possible_close_selectors:
                try:
                    page.locator(selector).first.click(timeout=700)
                    page.wait_for_timeout(300)
                except Exception:
                    pass

            page.screenshot(path=str(out_path), full_page=False, type="png")
        except PlaywrightTimeoutError:
            raise HTTPException(status_code=504, detail="TradingView grafiği zamanında yüklenmedi.")
        finally:
            browser.close()

    return out_path, f"/screenshots/{filename}"



def http_get_text(url: str, timeout: int = 12) -> tuple[str, str | None]:
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122 Safari/537.36",
        "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    try:
        r = requests.get(url, headers=headers, timeout=timeout)
        r.raise_for_status()
        return r.text, None
    except Exception as e:
        return "", f"{type(e).__name__}: {e}"


def tr_number_to_float(value: str):
    if value is None:
        return None
    v = str(value).strip().replace("%", "").replace("+", "")
    v = re.sub(r"[^0-9,.-]", "", v)
    if not v:
        return None
    # TR format: 1.234.567,89 -> 1234567.89
    if "," in v:
        v = v.replace(".", "").replace(",", ".")
    try:
        return float(v)
    except Exception:
        return None


def lines_from_html(html: str) -> list[str]:
    text = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.I)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "\n", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    lines = [re.sub(r"\s+", " ", x).strip() for x in text.splitlines()]
    return [x for x in lines if x]


def parse_symbol_block(lines: list[str], symbol: str) -> dict | None:
    sym = normalize_symbol(symbol)
    numeric_re = re.compile(r"^[+-]?\d{1,3}(?:\.\d{3})*(?:,\d+)?%?$|^[+-]?\d+(?:,\d+)?%?$")
    for i, line in enumerate(lines):
        tokens = line.upper().split()
        # Tam sembol eşleşsin; şirket adında geçişlerden kaçınmak için ilk birkaç token yeterli.
        if sym in tokens[:3] or line.upper() == sym:
            nums = []
            for nxt in lines[i + 1:i + 12]:
                cleaned = nxt.replace("−", "-")
                if numeric_re.match(cleaned):
                    nums.append(cleaned)
                if len(nums) >= 6:
                    break
            if nums:
                out = {"symbol": sym, "raw_label": line, "raw_values": nums}
                # Genel tablo sıralaması: son/alış/satış/fark%/düşük/yüksek/aof/hacim TL/hacim lot olabilir.
                out["last"] = tr_number_to_float(nums[0])
                if len(nums) > 1:
                    out["change_or_bid"] = tr_number_to_float(nums[1])
                if len(nums) > 2:
                    out["change_percent_or_ask"] = tr_number_to_float(nums[2])
                return out
    return None


def fetch_midas_quote(symbol: str) -> dict:
    url = "https://www.getmidas.com/canli-borsa/"
    html, err = http_get_text(url)
    if err:
        return {"provider": "Midas Canlı Borsa", "status": "error", "url": url, "note": err}
    block = parse_symbol_block(lines_from_html(html), symbol)
    if not block:
        return {"provider": "Midas Canlı Borsa", "status": "not_found", "url": url, "note": "Sembol tabloda bulunamadı veya sayfa dinamik değişti."}
    block.update({"provider": "Midas Canlı Borsa", "status": "ok", "url": url, "note": "Midas canlı borsa sayfası 15 dakika gecikmeli olabilir; son/alış/satış/düşük-yüksek/AOF/hacim alanları tabloda bulunursa raw_values içinde döner."})
    return block


def fetch_bloomberght_quote(symbol: str) -> dict:
    url = "https://www.bloomberght.com/borsa"
    html, err = http_get_text(url)
    if err:
        return {"provider": "BloombergHT Borsa", "status": "error", "url": url, "note": err}
    block = parse_symbol_block(lines_from_html(html), symbol)
    if not block:
        return {"provider": "BloombergHT Borsa", "status": "not_found", "url": url, "note": "Sembol görünür borsa listelerinde bulunamadı; sayfa yalnızca öne çıkan/çok işlem görenleri gösterebilir."}
    block.update({"provider": "BloombergHT Borsa", "status": "ok", "url": url, "note": "BloombergHT görünür borsa tablosundan özet fiyat teyidi."})
    return block


def fetch_investing_quote(symbol: str) -> dict:
    url = "https://tr.investing.com/"
    html, err = http_get_text(url)
    if err:
        return {"provider": "Investing.com TR", "status": "error", "url": url, "note": err}
    block = parse_symbol_block(lines_from_html(html), symbol)
    if not block:
        return {"provider": "Investing.com TR", "status": "not_found", "url": url, "note": "Ana sayfada sembol bulunamadı; Investing sayfaları dinamik/korumalı olabilir. Yine de kaynak durumuna raporlandı."}
    block.update({"provider": "Investing.com TR", "status": "ok", "url": url, "note": "Investing TR görünür piyasa listelerinden özet fiyat teyidi; grafik/intraday mum API değildir."})
    return block


def fetch_bist_reference(symbol: str) -> dict:
    url = "https://www.borsaistanbul.com/"
    html, err = http_get_text(url)
    if err:
        return {"provider": "Borsa İstanbul", "status": "error", "url": url, "note": err}
    # Resmi site çoğunlukla canlı intraday OHLC tablosu değil; veri menülerinin erişilebilirliğini doğrular.
    has_data_menu = ("Pay Piyasası Verileri" in html) or ("Günlük Bülten" in html) or ("Veriler" in html)
    return {
        "provider": "Borsa İstanbul",
        "status": "reference_ok" if has_data_menu else "reference_limited",
        "url": url,
        "symbol": normalize_symbol(symbol),
        "note": "Resmi Borsa İstanbul sitesi veri/duyuru/günlük bülten referansı olarak kullanılır; ücretsiz canlı 1dk/5dk mum verisi kaynağı gibi davranmaz. Intraday grafik için TradingView; özet fiyat için Midas/Investing/BloombergHT kullanılır."
    }


def fetch_public_quote_snapshots(symbol: str) -> tuple[list[dict], dict]:
    quotes = []
    for fn in (fetch_midas_quote, fetch_bloomberght_quote, fetch_investing_quote):
        try:
            quotes.append(fn(symbol))
        except Exception as e:
            quotes.append({"provider": fn.__name__, "status": "error", "note": f"{type(e).__name__}: {e}"})
    try:
        official = fetch_bist_reference(symbol)
    except Exception as e:
        official = {"provider": "Borsa İstanbul", "status": "error", "note": f"{type(e).__name__}: {e}"}
    return quotes, official


def flatten_yfinance_columns(df: pd.DataFrame) -> pd.DataFrame:
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [str(c[0]) for c in df.columns]
    return df


def clean_ohlc_df(df: pd.DataFrame, target_date: Optional[str], max_rows: int = 160) -> list[dict]:
    if df is None or df.empty:
        return []

    df = flatten_yfinance_columns(df).copy()
    df = df.dropna(how="all")

    if target_date:
        wanted = pd.to_datetime(target_date).date()
        try:
            idx_dates = pd.to_datetime(df.index).date
            same_day = df.loc[idx_dates == wanted]
            if not same_day.empty:
                df = same_day
        except Exception:
            pass

    if df.empty:
        return []

    df = df.reset_index().tail(max_rows)
    rows = []
    for _, r in df.iterrows():
        dt_val = r.get("Datetime", r.get("Date", r.iloc[0] if len(r) else ""))
        row = {
            "time": str(dt_val),
            "open": None if pd.isna(r.get("Open")) else round(float(r.get("Open")), 4),
            "high": None if pd.isna(r.get("High")) else round(float(r.get("High")), 4),
            "low": None if pd.isna(r.get("Low")) else round(float(r.get("Low")), 4),
            "close": None if pd.isna(r.get("Close")) else round(float(r.get("Close")), 4),
            "volume": None if pd.isna(r.get("Volume")) else int(float(r.get("Volume"))),
        }
        if any(row[k] is not None for k in ["open", "high", "low", "close", "volume"]):
            rows.append(row)
    return rows


def read_cache(cache_key: str):
    cached = OHLC_CACHE.get(cache_key)
    if not cached:
        return None
    ts, rows, status, note, provider = cached
    if time.time() - ts > CACHE_TTL_SECONDS:
        OHLC_CACHE.pop(cache_key, None)
        return None
    return rows, status, note + " Cache kullanıldı; gereksiz Yahoo isteği yapılmadı.", provider


def write_cache(cache_key: str, rows: list[dict], status: str, note: str, provider: str):
    if rows:
        OHLC_CACHE[cache_key] = (time.time(), rows, status, note, provider)


def stooq_symbol(symbol: str) -> str:
    # Stooq BIST günlük verilerinde genelde thyao.tr / asels.tr formatı kullanılır.
    return f"{normalize_symbol(symbol).lower()}.tr"


def fetch_stooq_daily(symbol: str, target_date: Optional[str], max_rows: int = 160) -> tuple[list[dict], str, str]:
    base_note = (
        "Stooq günlük OHLC fallback katmanı kullanıldı. "
        "Bu kaynak intraday mum doğrulaması için değil, günlük açılış-yüksek-düşük-kapanış/hacim teyidi içindir."
    )
    url = f"https://stooq.com/q/d/l/?s={stooq_symbol(symbol)}&i=d"
    try:
        df = pd.read_csv(url)
        if df is None or df.empty:
            return [], "no_stooq_data", base_note + " Stooq veri döndürmedi."
        df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
        df = df.dropna(subset=["Date"])
        if target_date:
            wanted = pd.to_datetime(target_date).date()
            same_day = df.loc[df["Date"].dt.date == wanted]
            if not same_day.empty:
                df = same_day
            else:
                # Belirtilen güne veri yoksa hedef tarih çevresindeki son kayıtları döndür.
                df = df.loc[df["Date"].dt.date <= wanted].tail(max_rows)
        else:
            df = df.tail(max_rows)
        rows = []
        for _, r in df.iterrows():
            row = {
                "time": str(r.get("Date", "")),
                "open": None if pd.isna(r.get("Open")) else round(float(r.get("Open")), 4),
                "high": None if pd.isna(r.get("High")) else round(float(r.get("High")), 4),
                "low": None if pd.isna(r.get("Low")) else round(float(r.get("Low")), 4),
                "close": None if pd.isna(r.get("Close")) else round(float(r.get("Close")), 4),
                "volume": None if pd.isna(r.get("Volume")) else int(float(r.get("Volume"))),
            }
            rows.append(row)
        if rows:
            return rows, "stooq_daily_fallback", base_note
        return [], "no_stooq_data", base_note + " Stooq satırları temizlenemedi."
    except Exception as e:
        return [], "stooq_error", base_note + f" Stooq hatası: {type(e).__name__}: {e}"


def yf_download_with_fallbacks(yf_symbol: str, yf_interval: str, period: str, target_date: Optional[str], plain_symbol: str) -> tuple[list[dict], str, str, str]:
    cache_key = f"{yf_symbol}:{yf_interval}:{period}:{target_date or 'latest'}"
    cached = read_cache(cache_key)
    if cached:
        return cached

    base_note = (
        "Yahoo Finance doğrulama/eksik veri tamamlama katmanı kullanıldı. "
        "BIST intraday verileri ücretsiz kaynaklarda gecikmeli, sınırlı veya dönemsel olarak eksik olabilir. "
        "Mikro yapı/derinlik/AKD/BOFA için aracı kurum ekranı gerekir."
    )

    attempts: list[dict] = []

    if target_date:
        try:
            d = datetime.strptime(target_date, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(status_code=400, detail="target_date YYYY-MM-DD formatında olmalı. Örn: 2026-06-04")

        attempts.append({"mode": "download_date_intraday", "start": d - timedelta(days=4), "end": d + timedelta(days=4), "interval": yf_interval})
        attempts.append({"mode": "download_date_daily", "start": d - timedelta(days=14), "end": d + timedelta(days=14), "interval": "1d"})
    else:
        safe_period = period if period in YF_ALLOWED_PERIODS else "5d"
        attempts.append({"mode": "download_period", "period": safe_period, "interval": yf_interval})
        if yf_interval != "1d":
            attempts.append({"mode": "download_period_daily", "period": "3mo" if safe_period in {"1mo", "3mo", "6mo", "1y"} else "1mo", "interval": "1d"})

    last_error = None

    for attempt in attempts:
        try:
            if "period" in attempt:
                df = yf.download(
                    yf_symbol,
                    period=attempt["period"],
                    interval=attempt["interval"],
                    progress=False,
                    auto_adjust=False,
                    threads=False,
                )
            else:
                df = yf.download(
                    yf_symbol,
                    start=attempt["start"].isoformat(),
                    end=attempt["end"].isoformat(),
                    interval=attempt["interval"],
                    progress=False,
                    auto_adjust=False,
                    threads=False,
                )
            rows = clean_ohlc_df(df, target_date=target_date)
            if rows:
                if attempt["interval"] != yf_interval:
                    status = "partial_yahoo_daily_fallback"
                    note = base_note + f" İstenen Yahoo intervali bulunamadı; fallback olarak {attempt['interval']} döndü."
                    write_cache(cache_key, rows, status, note, "Yahoo Finance")
                    return rows, status, note, "Yahoo Finance"
                status = "ok"
                note = base_note
                write_cache(cache_key, rows, status, note, "Yahoo Finance")
                return rows, status, note, "Yahoo Finance"
        except Exception as e:
            last_error = f"{type(e).__name__}: {e}"
            if "RateLimit" in type(e).__name__ or "Too Many Requests" in str(e):
                break

    try:
        ticker = yf.Ticker(yf_symbol)
        if target_date:
            d = datetime.strptime(target_date, "%Y-%m-%d").date()
            df = ticker.history(start=(d - timedelta(days=14)).isoformat(), end=(d + timedelta(days=14)).isoformat(), interval="1d", auto_adjust=False)
        else:
            df = ticker.history(period="1mo", interval=yf_interval, auto_adjust=False)
        rows = clean_ohlc_df(df, target_date=target_date)
        if rows:
            status = "ok_ticker_history"
            note = base_note + " Veri yfinance Ticker.history fallback yöntemiyle alındı."
            write_cache(cache_key, rows, status, note, "Yahoo Finance")
            return rows, status, note, "Yahoo Finance"
    except Exception as e:
        last_error = f"{type(e).__name__}: {e}"

    stooq_rows, stooq_status, stooq_note = fetch_stooq_daily(plain_symbol, target_date=target_date)
    if stooq_rows:
        note = (
            base_note
            + " Yahoo Finance veri veremedi; eksik veri tamamlama için Stooq günlük OHLC fallback kullanıldı. "
            + stooq_note
        )
        if last_error:
            note += f" Yahoo son hata: {last_error}"
        write_cache(cache_key, stooq_rows, stooq_status, note, "Stooq Daily")
        return stooq_rows, stooq_status, note, "Stooq Daily"

    msg = base_note + " Yahoo Finance veri bulunamadı. Sembol .IS formatıyla denendi. Stooq günlük fallback de veri döndüremedi."
    if last_error:
        msg += f" Son hata: {last_error}"
    msg += " Grafik screenshot yine de TradingView'den alındı; görsel analiz yapılabilir fakat sayısal OHLC doğrulaması eksik işaretlenmelidir."
    return [], "no_data_all_sources", msg, "none"

def fetch_yahoo_ohlc(symbol: str, interval: str, period: str, target_date: Optional[str]) -> tuple[list[dict], str, str, str, str]:
    yf_symbol = make_yahoo_symbol(symbol)
    yf_interval = YF_INTERVALS.get(interval, "5m")
    rows, status, note, provider = yf_download_with_fallbacks(yf_symbol, yf_interval, period, target_date, plain_symbol=symbol)
    note = note + f" Veri sağlayıcı durumu: {provider}."
    return rows, status, note, yf_symbol, yf_interval


@app.get("/chart", response_model=ChartResponse)
def get_chart(
    request: Request,
    symbol: str = Query(..., description="BIST sembolü. Örn: THYAO, ASELS, TUPRS"),
    interval: Literal["1m", "3m", "5m", "10m", "15m", "30m", "1h", "1d"] = Query("5m"),
    range_hint: str = Query("5d", description="1d, 5d, 1mo, 3mo, 6mo, 1y gibi niyet bilgisi"),
    target_date: Optional[str] = Query(None, description="YYYY-MM-DD. Örn: 2026-06-04"),
    include_base64: bool = Query(False, description="true ise screenshot_base64_png de döner. Cevabı çok büyütür; normalde false kalsın."),
):
    s = normalize_symbol(symbol)
    url = make_tv_url(s, interval)
    image_path, image_route = screenshot_tradingview(url, symbol=s, interval=interval)

    ohlc, status, note, yf_symbol, yf_interval = fetch_yahoo_ohlc(s, interval, range_hint, target_date)
    quote_snapshots, official_reference = fetch_public_quote_snapshots(s)
    ok_quote_providers = [q.get("provider") for q in quote_snapshots if q.get("status") == "ok"]
    if ok_quote_providers:
        note += " Ek ücretsiz fiyat teyit kaynakları başarılı: " + ", ".join(ok_quote_providers) + "."
    else:
        note += " Ek ücretsiz fiyat teyit kaynaklarından doğrudan sembol bazlı sonuç alınamadı; kaynak durumları quote_snapshots içinde raporlandı."

    image_b64 = None
    if include_base64:
        image_b64 = base64.b64encode(image_path.read_bytes()).decode("utf-8")

    return ChartResponse(
        symbol=s,
        yahoo_symbol=yf_symbol,
        interval=interval,
        yahoo_interval_used=yf_interval,
        range_hint=range_hint,
        target_date=target_date,
        source_chart="TradingView visual chart screenshot",
        source_data="Yahoo Finance OHLC + Stooq daily + Midas/Investing/BloombergHT quote verification + Borsa İstanbul official reference + in-memory cache",
        tradingview_url=url,
        screenshot_url=absolute_url(request, image_route),
        screenshot_base64_png=image_b64,
        ohlc_sample=ohlc,
        ohlc_count=len(ohlc),
        quote_snapshots=quote_snapshots,
        official_reference=official_reference,
        data_status=status,
        data_note=note,
        captured_at_utc=datetime.now(timezone.utc).isoformat(),
    )
