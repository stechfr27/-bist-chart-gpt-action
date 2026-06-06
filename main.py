import base64
import html as html_lib
import os
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
import asyncio
from PIL import Image
from typing import Optional

import pandas as pd
import requests
import yfinance as yf
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from playwright.async_api import Browser, BrowserContext, Page, TimeoutError as PlaywrightTimeoutError, async_playwright
from pydantic import BaseModel, Field

APP_VERSION = "2.6.0-graph-first-current"
SCREENSHOT_DIR = Path(os.getenv("SCREENSHOT_DIR", "/tmp/bist_chart_screenshots"))
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
CACHE_TTL_SECONDS = int(os.getenv("OHLC_CACHE_TTL_SECONDS", "300"))
QUOTE_CACHE_TTL_SECONDS = int(os.getenv("QUOTE_CACHE_TTL_SECONDS", "180"))
TRADINGVIEW_COOKIE = os.getenv("TRADINGVIEW_COOKIE", "").strip()
TV_WAIT_CURRENT_MS = int(os.getenv("TV_WAIT_CURRENT_MS", "1200"))
TV_WAIT_BALANCED_MS = int(os.getenv("TV_WAIT_BALANCED_MS", "9000"))
TV_CANVAS_WAIT_CURRENT_MS = int(os.getenv("TV_CANVAS_WAIT_CURRENT_MS", "1200"))
TV_CANVAS_WAIT_BALANCED_MS = int(os.getenv("TV_CANVAS_WAIT_BALANCED_MS", "9000"))
HTTP_TIMEOUT_CURRENT = int(os.getenv("HTTP_TIMEOUT_CURRENT", "2"))
HTTP_TIMEOUT_BALANCED = int(os.getenv("HTTP_TIMEOUT_BALANCED", "7"))
AUTO_CLEAR_SCREENSHOTS = os.getenv("AUTO_CLEAR_SCREENSHOTS", "true").lower() in {"1", "true", "yes", "on"}
SCREENSHOT_KEEP_LAST = int(os.getenv("SCREENSHOT_KEEP_LAST", "0"))
TV_CURRENT_HARD_TIMEOUT_SECONDS = int(os.getenv("TV_CURRENT_HARD_TIMEOUT_SECONDS", "55"))
TV_BALANCED_HARD_TIMEOUT_SECONDS = int(os.getenv("TV_BALANCED_HARD_TIMEOUT_SECONDS", "115"))
QUOTE_CURRENT_HARD_TIMEOUT_SECONDS = int(os.getenv("QUOTE_CURRENT_HARD_TIMEOUT_SECONDS", "2"))
TOTAL_CHART_HARD_TIMEOUT_SECONDS = int(os.getenv("TOTAL_CHART_HARD_TIMEOUT_SECONDS", "60"))
TV_SAFE_CURRENT_HARD_TIMEOUT_SECONDS = int(os.getenv("TV_SAFE_CURRENT_HARD_TIMEOUT_SECONDS", "75"))
TOTAL_SAFE_CURRENT_HARD_TIMEOUT_SECONDS = int(os.getenv("TOTAL_SAFE_CURRENT_HARD_TIMEOUT_SECONDS", "85"))
TOTAL_BALANCED_HARD_TIMEOUT_SECONDS = int(os.getenv("TOTAL_BALANCED_HARD_TIMEOUT_SECONDS", "115"))
USE_WIDGET_FOR_CURRENT = os.getenv("USE_WIDGET_FOR_CURRENT", "true").lower() in {"1", "true", "yes", "on"}

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
        self._lock = asyncio.Lock()
        self._pw = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self.started_at = None

    async def get_context(self) -> BrowserContext:
        async with self._lock:
            if self._context:
                return self._context
            self._pw = await async_playwright().start()
            self._browser = await self._pw.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--disable-features=IsolateOrigins,site-per-process",
                ],
            )
            extra_headers = {}
            if TRADINGVIEW_COOKIE:
                extra_headers["Cookie"] = TRADINGVIEW_COOKIE
            self._context = await self._browser.new_context(
                viewport={"width": 1280, "height": 760},
                device_scale_factor=1,
                locale="tr-TR",
                timezone_id="Europe/Istanbul",
                extra_http_headers=extra_headers,
                user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36",
            )
            self.started_at = datetime.now(timezone.utc).isoformat()
            return self._context

    async def reset(self):
        async with self._lock:
            try:
                if self._context:
                    await self._context.close()
            except Exception:
                pass
            try:
                if self._browser:
                    await self._browser.close()
            except Exception:
                pass
            try:
                if self._pw:
                    await self._pw.stop()
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
    performance_note: str = ""
    captured_at_utc: str

app = FastAPI(
    title="BIST Chart GPT Action API",
    description="ChatGPT Actions compatible BIST chart service: TradingView screenshot + Yahoo/Stooq/Midas/BloombergHT/Investing/Borsa Istanbul verification layers.",
    version=APP_VERSION,
)
app.mount("/screenshots", StaticFiles(directory=str(SCREENSHOT_DIR)), name="screenshots")

@app.on_event("shutdown")
async def shutdown_event():
    await BROWSER.reset()

@app.get("/")
def root():
    return {"ok": True, "service": "bist-chart-gpt-action", "version": APP_VERSION, "endpoints": ["/health", "/warmup", "/chart", "/screenshots-list", "/screenshots-clear"]}

@app.get("/health")
def health():
    return {"ok": True, "service": "bist-chart-gpt-action", "version": APP_VERSION, "browser_started_at": BROWSER.started_at}

@app.get("/warmup")
async def warmup():
    try:
        ctx = await BROWSER.get_context()
        page = await ctx.new_page()
        await install_fast_routes(page)
        await page.goto("https://tr.tradingview.com/chart/", wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(5000)
        await page.close()
        return {"ok": True, "version": APP_VERSION, "browser_started_at": BROWSER.started_at}
    except Exception as e:
        await BROWSER.reset()
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

def make_tv_widget_url(symbol: str, interval: str) -> str:
    tv_interval = TV_INTERVALS.get(interval, "5")
    # Lightweight official TradingView widget. Much faster than the full /chart app and still renders real candles.
    return (
        "https://s.tradingview.com/widgetembed/?"
        f"symbol=BIST%3A{symbol}&interval={tv_interval}&hidesidetoolbar=1&symboledit=1&saveimage=0"
        "&toolbarbg=f1f3f6&studies=[]&theme=light&style=1&timezone=Europe%2FIstanbul"
        "&withdateranges=1&hideideas=1&studies_overrides={}&overrides={}&enabled_features=[]&disabled_features=[]"
        "&locale=tr"
    )

def absolute_url(request: Request, path: str) -> str:
    return f"{str(request.base_url).rstrip('/')}{path}"

async def install_fast_routes(page: Page):
    """Block non-essential heavy resources while keeping TradingView JS/canvas intact."""
    async def _route(route):
        try:
            req = route.request
            rtype = req.resource_type
            url = req.url.lower()
            if rtype in {"font", "media"}:
                await route.abort()
                return
            if any(x in url for x in ["doubleclick", "googlesyndication", "google-analytics", "analytics", "hotjar", "facebook", "adservice"]):
                await route.abort()
                return
            await route.continue_()
        except Exception:
            try:
                await route.continue_()
            except Exception:
                pass
    try:
        await page.route("**/*", _route)
    except Exception:
        pass

async def click_soft_popups(page: Page):
    selectors = [
        "button[aria-label='Close']", "button[aria-label='Kapat']", "button[data-name='close']",
        "button:has-text('Accept')", "button:has-text('Kabul')", "button:has-text('Tümünü kabul et')",
        "button:has-text('I understand')", "button:has-text('Anladım')", "button:has-text('Later')",
    ]
    for selector in selectors:
        try:
            await page.locator(selector).first.click(timeout=600)
            await page.wait_for_timeout(250)
        except Exception:
            pass


def screenshot_has_chart_content(path: Path) -> bool:
    """Reject blank/loading TradingView screenshots before giving them to GPT.
    The check focuses on the main chart canvas area and ignores right watchlist panels.
    """
    try:
        img = Image.open(path).convert("RGB")
        w, h = img.size
        # Main TradingView chart area for our 1440x950 viewport. Exclude left toolbar/right watchlist/top bar as much as possible.
        left = int(w * 0.045)
        top = int(h * 0.07)
        right = int(w * 0.97)
        bottom = int(h * 0.93)
        crop = img.crop((left, top, right, bottom))
        pixels = crop.getdata()
        total = max(1, crop.size[0] * crop.size[1])
        non_white = 0
        dark = 0
        colorish = 0
        for r, g, b in pixels:
            if r < 245 or g < 245 or b < 245:
                non_white += 1
            if r < 205 and g < 205 and b < 205:
                dark += 1
            if max(r, g, b) - min(r, g, b) > 28 and min(r, g, b) < 235:
                colorish += 1
        non_white_ratio = non_white / total
        dark_ratio = dark / total
        colorish_ratio = colorish / total
        # A loading/blank chart is almost completely white in the main plot area.
        # Real candles/volume/grid/legend typically push these above the thresholds.
        return (non_white_ratio >= 0.018) or (dark_ratio >= 0.010) or (colorish_ratio >= 0.004)
    except Exception:
        # If validation itself fails, be conservative and do not trust the image.
        return False

async def capture_and_validate(page: Page, out_path: Path, img_type: str, quality: int) -> bool:
    if img_type == "jpeg":
        await page.screenshot(path=str(out_path), full_page=False, type="jpeg", quality=quality, timeout=7000)
    else:
        await page.screenshot(path=str(out_path), full_page=False, type="png", timeout=14000)
    return screenshot_has_chart_content(out_path)

async def _screenshot_single_url(url: str, symbol: str, interval: str, mode: str, source_kind: str) -> tuple[Optional[Path], Optional[str], str, str]:
    img_type = "jpeg" if mode in {"current", "fast", "safe_current"} else "png"
    ext = "jpg" if img_type == "jpeg" else "png"
    filename = f"{symbol}_{interval}_{source_kind}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{uuid.uuid4().hex[:8]}.{ext}"
    out_path = SCREENSHOT_DIR / filename
    ctx = await BROWSER.get_context()
    page = None
    try:
        page = await ctx.new_page()
        await install_fast_routes(page)
        page.set_default_timeout(8000 if mode == "safe_current" else (5000 if mode in {"current", "fast"} else 12000))
        page.set_default_navigation_timeout(45000 if mode == "safe_current" else (28000 if mode in {"current", "fast"} else 55000))
        await page.goto(url, wait_until="domcontentloaded", timeout=45000 if mode == "safe_current" else (28000 if mode in {"current", "fast"} else 55000))
        await click_soft_popups(page)
        base_wait = (2200 if mode == "safe_current" else TV_WAIT_CURRENT_MS) if mode in {"current", "fast", "safe_current"} else TV_WAIT_BALANCED_MS
        canvas_wait = (1500 if mode == "safe_current" else TV_CANVAS_WAIT_CURRENT_MS) if mode in {"current", "fast", "safe_current"} else TV_CANVAS_WAIT_BALANCED_MS
        max_attempts = 5 if mode == "safe_current" else (3 if mode in {"current", "fast"} else 5)
        last_validation_note = ""
        for attempt in range(1, max_attempts + 1):
            await page.wait_for_timeout(base_wait if attempt == 1 else (2200 if mode == "safe_current" else (1400 if mode in {"current", "fast"} else 3500)))
            canvas_found = False
            for selector in ["canvas", "div.chart-container", "div.tv-lightweight-charts", "div[data-name='legend-source-item']", "div[data-name='legend']"]:
                try:
                    await page.locator(selector).first.wait_for(state="visible", timeout=canvas_wait)
                    canvas_found = True
                    break
                except Exception:
                    pass
            try:
                verified_image = await capture_and_validate(page, out_path, img_type, 78 if img_type == "jpeg" else 0)
                if verified_image:
                    status = "ok" if canvas_found else "ok_visual_verified"
                    note = f"TradingView {source_kind} screenshot captured and visual content check passed."
                    return out_path, f"/screenshots/{filename}", status, note
                last_validation_note = f"attempt {attempt}: image looked blank/loading"
            except Exception as shot_error:
                last_validation_note = f"attempt {attempt}: screenshot error {type(shot_error).__name__}: {shot_error}"
        try:
            if out_path.exists():
                out_path.unlink()
        except Exception:
            pass
        return None, None, "chart_loading_not_captured", f"TradingView {source_kind} did not pass visual validation; blank/loading image was rejected. {last_validation_note}"
    except Exception as e:
        try:
            if out_path.exists():
                out_path.unlink()
        except Exception:
            pass
        return None, None, "chart_failed_data_only", f"TradingView {source_kind} screenshot failed. Error: {type(e).__name__}: {e}"
    finally:
        try:
            if page:
                await page.close()
        except Exception:
            pass

async def screenshot_tradingview(url: str, symbol: str, interval: str, mode: str = "current") -> tuple[Optional[Path], Optional[str], str, str]:
    """Graph-first, timeboxed TradingView capture.
    For current/safe_current the priority is NOT quote data; it is getting a real, visually verified candle chart fast.
    It never returns a screenshot that fails the visual content check, so GPT won't analyze loading screens.
    """
    hard_timeout = TV_SAFE_CURRENT_HARD_TIMEOUT_SECONDS if mode == "safe_current" else (TV_CURRENT_HARD_TIMEOUT_SECONDS if mode in {"current", "fast"} else TV_BALANCED_HARD_TIMEOUT_SECONDS)

    async def _run():
        notes = []
        # Graph-first current mode: give the lightweight widget a short first chance, then spend the rest on full TradingView.
        # This avoids wasting the whole request on a stuck widget while still allowing the fastest path when it works.
        if mode in {"current", "fast", "safe_current"} and USE_WIDGET_FOR_CURRENT:
            widget_url = make_tv_widget_url(symbol, interval)
            widget_budget = 16 if mode in {"current", "fast"} else 22
            try:
                out_path, shot_path, status, note = await asyncio.wait_for(
                    _screenshot_single_url(widget_url, symbol, interval, mode, "widget"),
                    timeout=widget_budget,
                )
            except asyncio.TimeoutError:
                out_path, shot_path, status, note = None, None, "widget_timeboxed", f"TradingView widget timeboxed at {widget_budget}s; full chart fallback started."
            notes.append(note)
            if out_path and shot_path:
                return out_path, shot_path, status, note + " | Fast path: lightweight TradingView widget used."

        # Full chart gets the remaining budget. This is the most important layer because the user needs the visual graph.
        remaining_note = "Full TradingView chart fallback used; graph image is the priority layer."
        out_path, shot_path, status, note = await _screenshot_single_url(url, symbol, interval, mode, "full")
        if notes:
            note = " | ".join(notes + [remaining_note, note])
        return out_path, shot_path, status, note

    try:
        return await asyncio.wait_for(_run(), timeout=hard_timeout)
    except asyncio.TimeoutError:
        return None, None, "chart_timeboxed_no_image", f"TradingView graph capture timeboxed at {hard_timeout}s; no loading/blank screenshot was returned. Quote layers may still return."
    except Exception as e:
        await BROWSER.reset()
        return None, None, "chart_failed_data_only", f"TradingView graph capture failed; quote layers may still return. Error: {type(e).__name__}: {e}"

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

def http_get_text(url: str, timeout: int = 10) -> tuple[str, Optional[str]]:
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/122 Safari/537.36",
        "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    try:
        r = requests.get(url, headers=headers, timeout=timeout)
        r.raise_for_status()
        content_type = r.headers.get("content-type", "").lower()
        # Turkish finance pages are usually UTF-8; requests may guess latin encodings and produce mojibake.
        if "charset=" in content_type:
            text = r.text
        else:
            try:
                text = r.content.decode("utf-8")
            except Exception:
                r.encoding = r.apparent_encoding or "utf-8"
                text = r.text
        return repair_mojibake(text), None
    except Exception as e:
        return "", f"{type(e).__name__}: {e}"

def repair_mojibake(text: str) -> str:
    # Fix common UTF-8 decoded as latin-1/cp1252 artifacts seen as TÃ¼rk / Ä° / ÅŸ.
    if not text:
        return text
    suspicious = ("Ã", "Ä", "Å", "â€", "â€™", "&uuml;", "&ouml;", "&ccedil;")
    text = html_lib.unescape(text)
    if any(x in text for x in suspicious):
        for enc in ("latin1", "cp1252"):
            try:
                fixed = text.encode(enc, errors="ignore").decode("utf-8", errors="ignore")
                # Prefer the version with fewer mojibake markers, but avoid empty/over-short results.
                if len(fixed) > len(text) * 0.65 and sum(fixed.count(x) for x in ("Ã", "Ä", "Å", "â€")) < sum(text.count(x) for x in ("Ã", "Ä", "Å", "â€")):
                    text = fixed
                    break
            except Exception:
                pass
    replacements = {
        "Ä°": "İ", "Ä±": "ı", "ÅŸ": "ş", "Å": "Ş", "ÄŸ": "ğ", "Äž": "Ğ",
        "Ã¼": "ü", "Ãœ": "Ü", "Ã¶": "ö", "Ã–": "Ö", "Ã§": "ç", "Ã‡": "Ç",
        "â€™": "’", "â€˜": "‘", "â€œ": "“", "â€": "”", "â€“": "–", "â€”": "—",
    }
    for a, b in replacements.items():
        text = text.replace(a, b)
    return text

def to_ascii_tr(text: str) -> str:
    """Return an ASCII-safe version for clients that display UTF-8 JSON as mojibake."""
    if text is None:
        return text
    text = repair_mojibake(str(text))
    table = str.maketrans({
        "ç":"c", "Ç":"C", "ğ":"g", "Ğ":"G", "ı":"i", "İ":"I",
        "ö":"o", "Ö":"O", "ş":"s", "Ş":"S", "ü":"u", "Ü":"U",
        "’":"'", "‘":"'", "“":"\"", "”":"\"", "–":"-", "—":"-", "…":"...",
    })
    return text.translate(table)

def clean_html_text(html: str) -> list[str]:
    html = repair_mojibake(html)
    text = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.I)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "\n", text)
    text = html_lib.unescape(text)
    lines = [re.sub(r"\s+", " ", x).strip() for x in text.splitlines()]
    return [x for x in lines if x]

def extract_context_text(html: str, symbol: str, limit: int = 900) -> str:
    lines = clean_html_text(html)
    symbol_u = symbol.upper()
    useful_terms = (symbol_u, "BIST", "ALIS", "SATIS", "HACIM", "SON", "FIYAT", "%")
    skip_terms = ("sirket hakkinda", "ortaklik", "calisan", "nasil", "indirerek", "yorumlari", "haberleri")
    cleaned = []
    seen = set()
    for h in lines:
        h_fixed = to_ascii_tr(h).strip()
        h_low = h_fixed.lower()
        if len(h_fixed) < 2 or h_fixed in seen:
            continue
        if any(x in h_low for x in skip_terms):
            continue
        if any(term in h_fixed.upper() for term in useful_terms):
            seen.add(h_fixed)
            cleaned.append(h_fixed)
        if len(" | ".join(cleaned)) >= limit:
            break
    return " | ".join(cleaned)[:limit]

def make_quote_sources(symbol: str, mode: str = "balanced") -> list[tuple[str, str]]:
    midas_symbol = symbol.lower()
    sources = [
        ("Midas direct", f"https://www.getmidas.com/canli-borsa/{midas_symbol}-hisse/"),
    ]
    if mode not in {"current", "fast", "safe_current"}:
        sources.append(("Midas live table", "https://www.getmidas.com/canli-borsa/"))
    bloom_slug = BLOOMBERGHT_SLUGS.get(symbol.upper())
    if bloom_slug:
        sources.append(("BloombergHT direct", f"https://www.bloomberght.com/borsa/hisse/{bloom_slug}"))
    if mode not in {"current", "fast", "safe_current"}:
        sources.append(("BloombergHT borsa", "https://www.bloomberght.com/borsa"))
    inv_slug = INVESTING_SLUGS.get(symbol.upper())
    if mode not in {"current", "fast", "safe_current"}:
        if inv_slug:
            sources.append(("Investing direct", f"https://tr.investing.com/equities/{inv_slug}"))
        sources.append(("Investing search", f"https://tr.investing.com/search/?q={symbol}"))
    return sources

def fetch_public_quotes(symbol: str, mode: str = "balanced") -> tuple[list[dict], dict]:
    cache_key = f"quotes:{symbol}:{mode}"
    cached = QUOTE_CACHE.get(cache_key)
    if cached and time.time() - cached[0] < QUOTE_CACHE_TTL_SECONDS:
        return cached[1], cached[2]
    snapshots = []
    timeout = HTTP_TIMEOUT_CURRENT if mode in {"current", "fast", "safe_current"} else HTTP_TIMEOUT_BALANCED
    for name, url in make_quote_sources(symbol, mode):
        html, err = http_get_text(url, timeout=timeout)
        entry = {"source": name, "url": url, "status": "ok" if html else "error", "note": None, "context": None}
        if err:
            entry["note"] = to_ascii_tr(err)
        else:
            ctx_limit = 260 if mode in {"current", "fast", "safe_current"} else 900
            entry["context"] = to_ascii_tr(extract_context_text(html, symbol, ctx_limit))
            if name.startswith("Midas"):
                entry["note"] = "Midas live market page can be at least 15 minutes delayed from BIST; used as secondary price verification."
            if name.startswith("BloombergHT"):
                entry["note"] = "BloombergHT page is used as an additional price/percent/volume verification source."
            if name.startswith("Investing"):
                entry["note"] = "Investing page is used for additional price/percent and news context."
        snapshots.append(entry)
    official = {
        "source": "Borsa Istanbul",
        "status": "reference_only",
        "url": "https://www.borsaistanbul.com/",
        "note": "Official reference/news/daily bulletin source. Not used as a free live 1m/5m candle API.",
    }
    QUOTE_CACHE[cache_key] = (time.time(), snapshots, official)
    return snapshots, official

def build_ohlc(symbol: str, yahoo_symbol: str, interval: str, range_hint: str, target_date: Optional[str], mode: str = "balanced") :
    if mode in {"current", "safe_current"} and not target_date:
        return [], "current_quote_only", "Current mode: speed-first current chart; slow Yahoo/Stooq OHLC calls skipped. Price verification uses public quote layers."
    records, status, note = fetch_yahoo_ohlc(yahoo_symbol, interval, range_hint, target_date)
    if records:
        return records, status, note
    if mode == "fast":
        return [], "fast_no_ohlc", f"{note} | Fast mode: Stooq daily fallback skipped."
    stooq_records, stooq_status, stooq_note = fetch_stooq_daily(symbol)
    combined_note = f"{note} | {stooq_note}"
    if stooq_records:
        return stooq_records, stooq_status, combined_note
    return [], "no_ohlc_all_sources", combined_note


def clear_screenshot_files(keep_last: int = 0) -> dict:
    all_files = sorted([p for p in SCREENSHOT_DIR.glob("*") if p.is_file()], key=lambda x: x.stat().st_mtime, reverse=True)
    deleted = 0
    for p in all_files[keep_last:]:
        try:
            p.unlink()
            deleted += 1
        except Exception:
            pass
    return {"deleted": deleted, "kept": min(keep_last, len(all_files))}

@app.get("/screenshots-list")
def screenshots_list(limit: int = Query(30, ge=1, le=200)):
    files = []
    for p in sorted(SCREENSHOT_DIR.glob("*"), key=lambda x: x.stat().st_mtime, reverse=True)[:limit]:
        if p.is_file():
            files.append({"filename": p.name, "size_kb": round(p.stat().st_size / 1024, 1), "modified_utc": datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).isoformat(), "url_path": f"/screenshots/{p.name}"})
    return {"count": len(files), "files": files}

@app.post("/screenshots-clear")
def screenshots_clear(keep_last: int = Query(0, ge=0, le=500)):
    result = clear_screenshot_files(keep_last=keep_last)
    return {"ok": True, **result}

@app.get("/chart", response_model=ChartResponse)
async def chart(
    request: Request,
    symbol: str = Query(..., description="BIST sembolü. Örn: THYAO, ASELS, TUPRS"),
    interval: str = Query("5m", description="1m, 3m, 5m, 10m, 15m, 30m, 1h, 1d"),
    range_hint: str = Query("5d", description="Yahoo period ipucu: 1d, 5d, 1mo, 3mo, 6mo, 1y..."),
    target_date: Optional[str] = Query(None, description="YYYY-MM-DD; tarihli analiz için doğrulama notu/veri aralığı."),
    include_base64: bool = Query(False, description="true ise screenshot base64 döner; genelde false kalsın."),
    mode: str = Query("current", description="current, safe_current, fast veya balanced. current guncel grafik icin graph-first 55sn moddur; safe_current 75sn daha guvenlidir; balanced tarihsel/OHLC icin detaylidir."),
    auto_clear: bool = Query(True, description="true ise yeni grafik isteginden once eski screenshot dosyalarini siler."),
):
    clean_symbol = normalize_symbol(symbol)
    if interval not in TV_INTERVALS:
        raise HTTPException(status_code=400, detail=f"Geçersiz interval: {interval}. Destek: {', '.join(TV_INTERVALS.keys())}")
    if mode not in {"current", "balanced", "fast", "safe_current"}:
        raise HTTPException(status_code=400, detail="mode current, safe_current, balanced veya fast olmalı.")
    if target_date and not re.match(r"^\d{4}-\d{2}-\d{2}$", target_date):
        raise HTTPException(status_code=400, detail="target_date YYYY-MM-DD formatında olmalı.")
    yahoo_symbol = make_yahoo_symbol(clean_symbol)
    tv_url = make_tv_url(clean_symbol, interval)

    clear_result = {"deleted": 0, "kept": 0}
    if auto_clear and AUTO_CLEAR_SCREENSHOTS:
        clear_result = clear_screenshot_files(keep_last=SCREENSHOT_KEEP_LAST)

    request_timeout = TOTAL_SAFE_CURRENT_HARD_TIMEOUT_SECONDS if mode == "safe_current" else (TOTAL_BALANCED_HARD_TIMEOUT_SECONDS if mode == "balanced" else TOTAL_CHART_HARD_TIMEOUT_SECONDS)
    screenshot_task = screenshot_tradingview(tv_url, clean_symbol, interval, mode)
    ohlc_task = run_in_threadpool(build_ohlc, clean_symbol, yahoo_symbol, interval, range_hint, target_date, mode)
    quotes_task = run_in_threadpool(fetch_public_quotes, clean_symbol, mode)
    try:
        (out_path, shot_path, chart_status, chart_note), (records, data_status, data_note), (quote_snapshots, official_reference) = await asyncio.wait_for(
            asyncio.gather(screenshot_task, ohlc_task, quotes_task),
            timeout=request_timeout,
        )
    except asyncio.TimeoutError:
        out_path, shot_path, chart_status, chart_note = None, None, "request_timeboxed_no_image", f"Request timeboxed at {request_timeout}s; no unverified image returned."
        records, data_status, data_note = [], "timeboxed_no_ohlc", "Slow OHLC layer was skipped by hard timeout."
        quote_snapshots, official_reference = [], {"source": "Borsa Istanbul", "status": "reference_only", "url": "https://www.borsaistanbul.com/", "note": "Official reference/news/daily bulletin source."}

    screenshot_base64 = None
    screenshot_url = absolute_url(request, shot_path) if shot_path else None
    if include_base64 and out_path and out_path.exists():
        screenshot_base64 = base64.b64encode(out_path.read_bytes()).decode("utf-8")

    final_note = to_ascii_tr(
        f"{chart_note} | Screenshot cleanup before capture: deleted={clear_result.get('deleted', 0)}, kept={clear_result.get('kept', 0)}. | {data_note} | Ucretsiz kaynaklarda BIST intraday verileri gecikmeli/sinirli/eksik olabilir. "
        "Mikro yapi, derinlik, AKD/BOFA ve karanlik oda icin araci kurum ekrani gerekir. "
        "GPT analizi once screenshot, sonra OHLC ve public quote teyitlerini birlikte degerlendirmelidir."
    )

    return ChartResponse(
        symbol=clean_symbol,
        yahoo_symbol=yahoo_symbol,
        interval=interval,
        yahoo_interval_used=YF_INTERVALS.get(interval, "5m"),
        range_hint=range_hint,
        target_date=target_date,
        source_chart="TradingView visual chart screenshot via persistent Playwright browser",
        source_data="Graph-first TradingView screenshot + non-blocking fast public quote checks; current=55s, safe_current=75s; Yahoo/Stooq OHLC only in balanced/dated modes + Borsa Istanbul official reference",
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
        performance_note=(("safe_current mode: 75s graph-first visual-safe TradingView capture + Midas/BloombergHT; Yahoo/Stooq skipped unless dated/balanced" if mode == "safe_current" else "current mode: graph-first 55s TradingView visual capture; quotes are non-blocking and slow OHLC is skipped") if mode in {"current", "fast", "safe_current"} else "balanced mode: slower OHLC fallback enabled"),
        captured_at_utc=datetime.now(timezone.utc).isoformat(),
    )
