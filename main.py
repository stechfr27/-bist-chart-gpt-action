import base64
import html as html_lib
import os
import re
import time
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
import asyncio
from PIL import Image
from typing import Optional, Any

try:
    import pandas as pd
except Exception:  # optional in graph-only runtime/tests
    pd = None
import requests
try:
    import yfinance as yf
except Exception:  # optional; graph-only endpoint does not call Yahoo
    yf = None
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from playwright.async_api import Browser, BrowserContext, Page, TimeoutError as PlaywrightTimeoutError, async_playwright
from pydantic import BaseModel, Field

APP_VERSION = "7.3.0-exact-range-forced-visual"
SCREENSHOT_DIR = Path(os.getenv("SCREENSHOT_DIR", "/tmp/bist_chart_screenshots"))
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
CACHE_TTL_SECONDS = int(os.getenv("OHLC_CACHE_TTL_SECONDS", "300"))
QUOTE_CACHE_TTL_SECONDS = int(os.getenv("QUOTE_CACHE_TTL_SECONDS", "180"))
TRADINGVIEW_COOKIE = os.getenv("TRADINGVIEW_COOKIE", "").strip()
BROWSERLESS_WS_ENDPOINT = os.getenv("BROWSERLESS_WS_ENDPOINT", "").strip()
TV_VIEWPORT_WIDTH = int(os.getenv("TV_VIEWPORT_WIDTH", "2400"))
TV_VIEWPORT_HEIGHT = int(os.getenv("TV_VIEWPORT_HEIGHT", "1350"))
TV_WAIT_CURRENT_MS = int(os.getenv("TV_WAIT_CURRENT_MS", "650"))
TV_WAIT_BALANCED_MS = int(os.getenv("TV_WAIT_BALANCED_MS", "9000"))
TV_CANVAS_WAIT_CURRENT_MS = int(os.getenv("TV_CANVAS_WAIT_CURRENT_MS", "650"))
TV_CANVAS_WAIT_BALANCED_MS = int(os.getenv("TV_CANVAS_WAIT_BALANCED_MS", "9000"))
HTTP_TIMEOUT_CURRENT = int(os.getenv("HTTP_TIMEOUT_CURRENT", "2"))
HTTP_TIMEOUT_BALANCED = int(os.getenv("HTTP_TIMEOUT_BALANCED", "7"))
AUTO_CLEAR_SCREENSHOTS = os.getenv("AUTO_CLEAR_SCREENSHOTS", "true").lower() in {"1", "true", "yes", "on"}
SCREENSHOT_KEEP_LAST = int(os.getenv("SCREENSHOT_KEEP_LAST", "0"))
TV_CURRENT_HARD_TIMEOUT_SECONDS = int(os.getenv("TV_CURRENT_HARD_TIMEOUT_SECONDS", os.getenv("CHART_TOTAL_TIMEOUT_SEC", os.getenv("TOTAL_CHART_HARD_TIMEOUT_SECONDS", "58"))))
TV_BALANCED_HARD_TIMEOUT_SECONDS = int(os.getenv("TV_BALANCED_HARD_TIMEOUT_SECONDS", "115"))
QUOTE_CURRENT_HARD_TIMEOUT_SECONDS = int(os.getenv("QUOTE_CURRENT_HARD_TIMEOUT_SECONDS", "2"))
TOTAL_CHART_HARD_TIMEOUT_SECONDS = int(os.getenv("TOTAL_CHART_HARD_TIMEOUT_SECONDS", os.getenv("CHART_TOTAL_TIMEOUT_SEC", "60")))
TV_SAFE_CURRENT_HARD_TIMEOUT_SECONDS = int(os.getenv("TV_SAFE_CURRENT_HARD_TIMEOUT_SECONDS", "75"))
TOTAL_SAFE_CURRENT_HARD_TIMEOUT_SECONDS = int(os.getenv("TOTAL_SAFE_CURRENT_HARD_TIMEOUT_SECONDS", "80"))
TOTAL_BALANCED_HARD_TIMEOUT_SECONDS = int(os.getenv("TOTAL_BALANCED_HARD_TIMEOUT_SECONDS", "115"))
USE_WIDGET_FOR_CURRENT = os.getenv("USE_WIDGET_FOR_CURRENT", "true").lower() in {"1", "true", "yes", "on"}
SESSION_ZOOM_STEPS = int(os.getenv("SESSION_ZOOM_STEPS", "8"))
SESSION_ZOOM_WHEEL_DELTA = int(os.getenv("SESSION_ZOOM_WHEEL_DELTA", "-620"))
SESSION_ZOOM_X_RATIO = float(os.getenv("SESSION_ZOOM_X_RATIO", "0.74"))
SESSION_ZOOM_Y_RATIO = float(os.getenv("SESSION_ZOOM_Y_RATIO", "0.58"))
CHART_ONLY_SCREENSHOT = os.getenv("CHART_ONLY_SCREENSHOT", "true").lower() in {"1", "true", "yes", "on"}
CHART_CLIP_WIDTH_RATIO = float(os.getenv("CHART_CLIP_WIDTH_RATIO", "1.00"))
CHART_CLIP_HEIGHT_RATIO = float(os.getenv("CHART_CLIP_HEIGHT_RATIO", "1.00"))
# For BIST current/session screenshots, crop out older sessions on the left so the latest trading day is wider.
# 0.0 = no left crop. Typical values: 0.30-0.42. Default tuned from THYAO 5m tests.
SESSION_LEFT_CROP_RATIO = float(os.getenv("SESSION_LEFT_CROP_RATIO", "0.00"))
BIST_SESSION_START = os.getenv("BIST_SESSION_START", "09:55")
BIST_SESSION_END = os.getenv("BIST_SESSION_END", "18:10")
BIST_SESSION_STRICT_NOTE = "BIST 5m session target is 09:55-18:10. For current requests, end target is current Istanbul time +1 minute, capped at 18:10. The system must not claim exact full-session coverage unless the x-axis visually shows that band."
TV_USE_CUSTOM_RANGE = os.getenv("TV_USE_CUSTOM_RANGE", "true").lower() in {"1", "true", "yes", "on"}
TV_CUSTOM_RANGE_CORE = os.getenv("TV_CUSTOM_RANGE_CORE", "true").lower() in {"1", "true", "yes", "on"}
TV_CUSTOM_RANGE_MAX_SECONDS = int(os.getenv("TV_CUSTOM_RANGE_MAX_SECONDS", os.getenv("TV_RANGE_MAX_SECONDS", "16")))
TV_CUSTOM_RANGE_START = os.getenv("TV_CUSTOM_RANGE_START", BIST_SESSION_START)
TV_CUSTOM_RANGE_END = os.getenv("TV_CUSTOM_RANGE_END", BIST_SESSION_END)
TV_CUSTOM_RANGE_CURRENT_PLUS_MINUTES = int(os.getenv("TV_CUSTOM_RANGE_CURRENT_PLUS_MINUTES", "1"))
# Exact visual mode: never return a screenshot as if it matched the request unless
# TradingView custom range UI reports that target range was filled and applied.
# This intentionally fails closed instead of returning a wrong multi-day image.
TV_REQUIRE_EXACT_RANGE = os.getenv("TV_REQUIRE_EXACT_RANGE", "true").lower() in {"1", "true", "yes", "on"}
TV_CUSTOM_RANGE_STRICT_FILL = os.getenv("TV_CUSTOM_RANGE_STRICT_FILL", "true").lower() in {"1", "true", "yes", "on"}
TV_CUSTOM_RANGE_OPEN_TIMEOUT_MS = int(os.getenv("TV_CUSTOM_RANGE_OPEN_TIMEOUT_MS", "1200"))
TV_IMAGE_DETECT_LAST_CANDLE = os.getenv("TV_IMAGE_DETECT_LAST_CANDLE", "true").lower() in {"1", "true", "yes", "on"}

# TradingView UI adjustment: try to maximize graph area and place the crosshair just above
# the latest candle column so TradingView's top legend/volume reflects the last candle.
TV_FORCE_FULLSCREEN = os.getenv("TV_FORCE_FULLSCREEN", "true").lower() in {"1", "true", "yes", "on"}
TV_FULLSCREEN_SHORTCUT = os.getenv("TV_FULLSCREEN_SHORTCUT", "Shift+F")
TV_HOVER_LAST_CANDLE = os.getenv("TV_HOVER_LAST_CANDLE", "true").lower() in {"1", "true", "yes", "on"}
TV_CLICK_LAST_CANDLE_COLUMN = os.getenv("TV_CLICK_LAST_CANDLE_COLUMN", "false").lower() in {"1", "true", "yes", "on"}
TV_LAST_CANDLE_X_RATIO = float(os.getenv("TV_LAST_CANDLE_X_RATIO", "0.965"))
TV_LAST_CANDLE_Y_RATIO = float(os.getenv("TV_LAST_CANDLE_Y_RATIO", "0.38"))

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
            # Browserless free sessions may close the remote browser/context between calls.
            # Never return a stale context if the browser is disconnected.
            if self._context and self._browser:
                try:
                    if self._browser.is_connected():
                        return self._context
                except Exception:
                    pass
                self._context = None
                self._browser = None
            self._pw = await async_playwright().start()
            extra_headers = {}
            if TRADINGVIEW_COOKIE:
                extra_headers["Cookie"] = TRADINGVIEW_COOKIE

            if BROWSERLESS_WS_ENDPOINT:
                # Remote browser mode: Browserless runs Chromium; this service only drives it.
                # The endpoint must be stored as a secret env var, e.g.
                # BROWSERLESS_WS_ENDPOINT=wss://chrome.browserless.io?token=...
                self._browser = await self._pw.chromium.connect_over_cdp(BROWSERLESS_WS_ENDPOINT, timeout=30000)
            else:
                # Local fallback mode for Render/Northflank Docker hosts.
                self._browser = await self._pw.chromium.launch(
                    headless=True,
                    args=[
                        "--no-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-gpu",
                        "--disable-features=IsolateOrigins,site-per-process",
                    ],
                )

            self._context = await self._browser.new_context(
                viewport={"width": TV_VIEWPORT_WIDTH, "height": TV_VIEWPORT_HEIGHT},
                device_scale_factor=1,
                locale="tr-TR",
                timezone_id="Europe/Istanbul",
                extra_http_headers=extra_headers,
                user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36",
            )
            self.started_at = datetime.now(timezone.utc).isoformat()
            return self._context

    async def new_page(self, label: str = ""):
        """Create a new page, rescuing stale Browserless contexts automatically.

        This is intentionally used instead of ctx.new_page() directly because
        Browserless free sessions can close an otherwise cached context between
        warmup and prepare/capture calls.
        """
        last_error = None
        for attempt in range(2):
            try:
                ctx = await self.get_context()
                return await ctx.new_page()
            except Exception as e:
                last_error = e
                msg = str(e).lower()
                if "closed" in msg or "target" in msg or "disconnected" in msg:
                    await self.reset()
                    continue
                raise
        raise last_error

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


PREPARED_CHARTS: dict[str, dict[str, Any]] = {}
PREPARE_SESSION_TTL_SECONDS = int(os.getenv("PREPARE_SESSION_TTL_SECONDS", "70"))
TV_PREPARE_GOTO_TIMEOUT_MS = int(os.getenv("TV_PREPARE_GOTO_TIMEOUT_MS", "12000"))
TV_PREPARE_POST_RANGE_WAIT_MS = int(os.getenv("TV_PREPARE_POST_RANGE_WAIT_MS", "1200"))

async def cleanup_prepared_charts():
    now = time.time()
    expired = []
    for sid, rec in list(PREPARED_CHARTS.items()):
        if rec.get("expires_at", 0) < now:
            expired.append(sid)
    for sid in expired:
        rec = PREPARED_CHARTS.pop(sid, None)
        page = rec.get("page") if rec else None
        try:
            if page:
                await page.close()
        except Exception:
            pass
    return expired

def _stage_list_from_note(note: str) -> list[str]:
    stages = []
    for part in (note or "").split("|"):
        part = part.strip()
        if part.startswith("stage=") or part.startswith("range_attempt") or part.startswith("target_") or part.startswith("goto"):
            stages.append(part)
    return stages

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
    range_attempt: dict = Field(default_factory=dict)
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
    description="ChatGPT Actions compatible BIST chart service: graph-only strict TradingView screenshot service. External market data is intentionally excluded.",
    version=APP_VERSION,
)
app.mount("/screenshots", StaticFiles(directory=str(SCREENSHOT_DIR)), name="screenshots")

@app.on_event("shutdown")
async def shutdown_event():
    await BROWSER.reset()

@app.get("/")
def root():
    return {"ok": True, "service": "bist-chart-gpt-action", "version": APP_VERSION, "endpoints": ["/health", "/warmup", "/prepare-chart", "/capture-chart", "/chart-agent", "/debug/range-target", "/chart", "/screenshots-list", "/screenshots-clear"]}

@app.get("/health")
def health():
    return {"ok": True, "service": "bist-chart-gpt-action", "version": APP_VERSION, "browser_started_at": BROWSER.started_at, "browserless_configured": bool(BROWSERLESS_WS_ENDPOINT), "browser_mode": "browserless_remote" if BROWSERLESS_WS_ENDPOINT else "local_fallback", "viewport": {"width": TV_VIEWPORT_WIDTH, "height": TV_VIEWPORT_HEIGHT}, "session_fit": {"zoom_steps": SESSION_ZOOM_STEPS, "wheel_delta": SESSION_ZOOM_WHEEL_DELTA, "x_ratio": SESSION_ZOOM_X_RATIO, "y_ratio": SESSION_ZOOM_Y_RATIO}, "chart_capture": {"chart_only": CHART_ONLY_SCREENSHOT, "clip_width_ratio": CHART_CLIP_WIDTH_RATIO, "clip_height_ratio": CHART_CLIP_HEIGHT_RATIO, "session_left_crop_ratio": SESSION_LEFT_CROP_RATIO}, "bist_session_target": {"start": BIST_SESSION_START, "end": BIST_SESSION_END, "strict_note": BIST_SESSION_STRICT_NOTE}, "tv_ui": {"force_fullscreen": TV_FORCE_FULLSCREEN, "hover_last_candle": TV_HOVER_LAST_CANDLE, "click_last_candle_column": TV_CLICK_LAST_CANDLE_COLUMN, "last_candle_x_ratio": TV_LAST_CANDLE_X_RATIO, "last_candle_y_ratio": TV_LAST_CANDLE_Y_RATIO, "image_detect_last_candle": TV_IMAGE_DETECT_LAST_CANDLE}, "custom_range": {"enabled": TV_USE_CUSTOM_RANGE, "core": TV_CUSTOM_RANGE_CORE, "max_seconds": TV_CUSTOM_RANGE_MAX_SECONDS, "env_aliases": {"CHART_TOTAL_TIMEOUT_SEC": os.getenv("CHART_TOTAL_TIMEOUT_SEC"), "TV_RANGE_MAX_SECONDS": os.getenv("TV_RANGE_MAX_SECONDS"), "TV_FULL_CHART_BUDGET_SECONDS": os.getenv("TV_FULL_CHART_BUDGET_SECONDS")}, "session_start": TV_CUSTOM_RANGE_START, "session_end": TV_CUSTOM_RANGE_END, "current_plus_minutes": TV_CUSTOM_RANGE_CURRENT_PLUS_MINUTES, "require_exact_range": TV_REQUIRE_EXACT_RANGE, "strict_fill": TV_CUSTOM_RANGE_STRICT_FILL, "range_attempt_json": True}, "prepare_capture": {"enabled": True, "ttl_seconds": PREPARE_SESSION_TTL_SECONDS, "active_sessions": len(PREPARED_CHARTS), "prepare_goto_timeout_ms": TV_PREPARE_GOTO_TIMEOUT_MS}}

@app.get("/debug/range-target")
async def debug_range_target(target_date: Optional[str] = None, view: str = "session"):
    """Dry-run the BIST session target calculation without opening TradingView.
    Useful before spending Browserless units.
    """
    if view not in {"session", "full_day", "day", "auto"}:
        raise HTTPException(status_code=400, detail="view session, full_day, day veya auto olmali.")
    window = build_target_session_window(target_date)
    return {
        "ok": True,
        "version": APP_VERSION,
        "view": view,
        "target_date": target_date,
        "target_start": window["start_label"],
        "target_end": window["end_label"],
        "session_start": TV_CUSTOM_RANGE_START,
        "session_end": TV_CUSTOM_RANGE_END,
        "current_plus_minutes": TV_CUSTOM_RANGE_CURRENT_PLUS_MINUTES,
        "strict_rule": "current: today 09:55 -> Istanbul now +1m capped 18:10; historical: target date 09:55 -> 18:10; 5m only",
    }

@app.get("/warmup")
async def warmup():
    """Start Chromium/context only.

    Do not navigate to TradingView here. Some free hosts can open Chromium but
    time out on TradingView during warmup; that made a healthy service look
    broken. The real TradingView load is tested only by /chart.
    """
    try:
        page = await BROWSER.new_page("warmup")
        await page.goto("about:blank", wait_until="load", timeout=8000)
        await page.close()
        return {
            "ok": True,
            "version": APP_VERSION,
            "browser_started_at": BROWSER.started_at,
            "warmup_mode": "browserless_remote" if BROWSERLESS_WS_ENDPOINT else "browser_only",
            "browserless_configured": bool(BROWSERLESS_WS_ENDPOINT),
            "viewport": {"width": TV_VIEWPORT_WIDTH, "height": TV_VIEWPORT_HEIGHT},
            "note": "Browser context is ready. TradingView is intentionally not loaded during warmup; use /chart to test real chart capture."
        }
    except Exception as e:
        await BROWSER.reset()
        raise HTTPException(status_code=503, detail=f"Warmup failed before TradingView: {type(e).__name__}: {e}")

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

def make_tv_url(symbol: str, interval: str, view: str = "session", target_date: Optional[str] = None) -> str:
    tv_interval = TV_INTERVALS.get(interval, "5")
    url = f"https://tr.tradingview.com/chart/?symbol=BIST:{symbol}&interval={tv_interval}"
    # Range=1D tells TradingView to fit the latest full trading day/session into view.
    # Unknown params are ignored by TradingView, so timestamp/date are best-effort for historical requests.
    if view in {"session", "full_day", "day"} or target_date:
        url += "&range=1D"
    if target_date:
        try:
            from datetime import datetime as _dt
            import zoneinfo as _zoneinfo
            dt = _dt.fromisoformat(target_date).replace(hour=12, minute=0, second=0, microsecond=0, tzinfo=_zoneinfo.ZoneInfo("Europe/Istanbul"))
            ts = int(dt.timestamp())
            url += f"&timestamp={ts}&time={ts}"
        except Exception:
            pass
    return url

def make_tv_widget_url(symbol: str, interval: str, view: str = "session") -> str:
    tv_interval = TV_INTERVALS.get(interval, "5")
    # Lightweight official TradingView widget. Much faster than the full /chart app and still renders real candles.
    return (
        "https://s.tradingview.com/widgetembed/?"
        f"symbol=BIST%3A{symbol}&interval={tv_interval}&hidesidetoolbar=1&symboledit=1&saveimage=0"
        + ("&range=1D" if view in {"session", "full_day", "day"} else "")
        + "&toolbarbg=f1f3f6&studies=[]&theme=light&style=1&timezone=Europe%2FIstanbul"
        "&withdateranges=1&hideideas=1&studies_overrides={}&overrides={}&enabled_features=[]&disabled_features=[]"
        "&locale=tr"
    )


def make_tv_local_html(symbol: str, interval: str, view: str = "session") -> str:
    tv_interval = TV_INTERVALS.get(interval, "5")
    # Local minimal TradingView Advanced Chart Widget page.
    # This is usually faster and cleaner than opening the full TradingView site on Render.
    html = f"""
<!doctype html>
<html>
<head>
  <meta charset='utf-8'>
  <meta name='viewport' content='width=device-width, initial-scale=1'>
  <title>BIST:{symbol} {tv_interval}</title>
  <style>
    html, body {{ margin:0; padding:0; width:100%; height:100%; overflow:hidden; background:#ffffff; }}
    #tv_chart_container {{ width:100vw; height:100vh; }}
    .fallback-note {{ position:absolute; top:8px; left:8px; z-index:1; font:12px Arial; color:#777; }}
  </style>
</head>
<body>
  <div id='tv_chart_container'></div>
  <script src='https://s3.tradingview.com/tv.js'></script>
  <script>
    function boot() {{
      if (!window.TradingView) {{ setTimeout(boot, 300); return; }}
      new TradingView.widget({{
        autosize: true,
        symbol: 'BIST:{symbol}',
        interval: '{tv_interval}',
        range: '1D',
        timezone: 'Europe/Istanbul',
        theme: 'light',
        style: '1',
        locale: 'tr',
        toolbar_bg: '#f1f3f6',
        enable_publishing: false,
        hide_side_toolbar: false,
        hide_top_toolbar: false,
        allow_symbol_change: false,
        save_image: false,
        container_id: 'tv_chart_container'
      }});
    }}
    boot();
  </script>
</body>
</html>
""".strip()
    return "data:text/html;charset=utf-8," + requests.utils.quote(html)

def make_midas_url(symbol: str) -> str:
    return f"https://www.getmidas.com/canli-borsa/{symbol.lower()}-hisse/"

def make_bloomberg_url(symbol: str) -> str:
    slug = BLOOMBERGHT_SLUGS.get(symbol, f"{symbol.lower()}-detay")
    return f"https://www.bloomberght.com/borsa/hisse/{slug}"

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
        "button:has-text('Tamam')",
    ]
    for selector in selectors:
        try:
            await page.locator(selector).first.click(timeout=600)
            await page.wait_for_timeout(250)
        except Exception:
            pass




def get_istanbul_now():
    try:
        import zoneinfo
        return datetime.now(zoneinfo.ZoneInfo("Europe/Istanbul"))
    except Exception:
        return datetime.utcnow().replace(tzinfo=timezone.utc) + timedelta(hours=3)

def _parse_hhmm(value: str) -> tuple[int, int]:
    try:
        h, m = value.strip().split(":")[:2]
        return max(0, min(23, int(h))), max(0, min(59, int(m)))
    except Exception:
        return 9, 45

def build_target_session_window(target_date: Optional[str]) -> dict:
    """Build the user's requested BIST session window.

    Current request: 09:55 -> Istanbul now +1m, capped at 18:10.
    Historical target_date: 09:55 -> 18:10 for that date.
    """
    now_tr = get_istanbul_now()
    sh, sm = _parse_hhmm(TV_CUSTOM_RANGE_START)
    eh, em = _parse_hhmm(TV_CUSTOM_RANGE_END)
    if target_date:
        try:
            base = datetime.fromisoformat(target_date).date()
            start_dt = datetime(base.year, base.month, base.day, sh, sm)
            end_dt = datetime(base.year, base.month, base.day, eh, em)
        except Exception:
            start_dt = now_tr.replace(hour=sh, minute=sm, second=0, microsecond=0)
            end_dt = now_tr.replace(hour=eh, minute=em, second=0, microsecond=0)
    else:
        start_dt = now_tr.replace(hour=sh, minute=sm, second=0, microsecond=0)
        hard_end = now_tr.replace(hour=eh, minute=em, second=0, microsecond=0)
        end_dt = now_tr + timedelta(minutes=TV_CUSTOM_RANGE_CURRENT_PLUS_MINUTES)
        if end_dt > hard_end:
            end_dt = hard_end
        if end_dt <= start_dt:
            end_dt = hard_end
    return {
        "start": start_dt,
        "end": end_dt,
        "start_label": start_dt.strftime("%d.%m.%Y %H:%M"),
        "end_label": end_dt.strftime("%d.%m.%Y %H:%M"),
        "date_label": start_dt.strftime("%d.%m.%Y"),
    }



def range_note_has_success(note: str) -> bool:
    """Return True only when the exact-range UI appears to have been filled and applied.

    This is intentionally strict. A plain TradingView screenshot is not enough for the
    user's visual-only GPT, because it can show multiple days. Exact mode must fail
    closed unless start/end fill and apply stages are both confirmed.
    """
    if not TV_USE_CUSTOM_RANGE:
        return False
    required = ["stage=fill_start_end ok=true", "stage=apply_range ok=true"]
    if TV_CUSTOM_RANGE_STRICT_FILL:
        required.append("stage=open_range_menu ok=true")
    return all(token in (note or "") for token in required)

def build_range_attempt_summary(target_date: Optional[str], view: str, chart_status: str = "", chart_note: str = "") -> dict:
    """Always expose the custom-range target and debug state as JSON.

    Previous v5.3 wrote range_attempt only into an internal page note. If Browserless
    or the top-level timeout closed the task before that note returned, the API response
    showed no range debug. This object is computed before capture and returned even on
    timeout/null screenshots.
    """
    window = build_target_session_window(target_date)
    note = chart_note or ""
    stages = []
    for part in note.split("|"):
        part = part.strip()
        if part.startswith("stage=") or part.startswith("range_attempt") or part.startswith("target_") or part.startswith("custom range"):
            stages.append(part)
    if not stages and "range_attempt" in note:
        stages.append(note)
    if chart_status in {"request_timeboxed_no_image", "strict_tradingview_image_failed"} or "timeboxed" in note.lower():
        status = "capture_or_range_timeboxed"
    elif "failed" in note.lower() or "error" in note.lower():
        status = "failed"
    elif "screenshot captured" in note.lower() or chart_status.startswith("ok"):
        status = "image_captured_verify_x_axis"
    else:
        status = "started_or_no_internal_note"
    return {
        "enabled": bool(TV_USE_CUSTOM_RANGE),
        "core": bool(TV_CUSTOM_RANGE_CORE),
        "view": view,
        "target_date": target_date,
        "target_start": window["start_label"],
        "target_end": window["end_label"],
        "session_start": TV_CUSTOM_RANGE_START,
        "session_end": TV_CUSTOM_RANGE_END,
        "current_plus_minutes": TV_CUSTOM_RANGE_CURRENT_PLUS_MINUTES,
        "max_seconds": TV_CUSTOM_RANGE_MAX_SECONDS,
        "status": status,
        "chart_status": chart_status,
        "stages": stages,
        "raw_note_excerpt": note[:900],
        "strict_rule": "current: today 09:55 -> Istanbul now +1m capped 18:10; historical: target date 09:55 -> 18:10; 5m only; do not claim exact session unless x-axis visually confirms it."
    }

async def try_tradingview_custom_date_range(page: Page, target_date: Optional[str], view: str) -> str:
    """Core range engine for BIST exact-session attempts.

    Current request target: today's 09:55 -> Istanbul now +1 minute, capped at 18:10.
    Historical request target: target_date 09:55 -> 18:10.

    This function is deliberately stage-logged. TradingView's public UI is not stable,
    so every step reports where it reached: open_range_menu, choose_custom_range,
    fill_start_end, apply, reload_wait. The API must not pretend the range succeeded
    unless the chart image later verifies visually.
    """
    if not TV_USE_CUSTOM_RANGE or view not in {"session", "full_day", "day"}:
        return "range_attempt enabled=false stage=skipped reason=not_session_view"

    window = build_target_session_window(target_date)
    notes = [
        "range_attempt enabled=true core=true",
        f"target_start={window['start_label']}",
        f"target_end={window['end_label']}",
        "rule=current_uses_istanbul_now_plus_1m_capped_18_10; historical_uses_09_55_to_18_10"
    ]

    def add(stage: str, ok: bool, detail: str = ""):
        notes.append(f"stage={stage} ok={str(ok).lower()}" + (f" detail={detail}" if detail else ""))

    try:
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(120)
    except Exception:
        pass

    # 1) Open the bottom-left/date-range control. Prefer coordinate path because the user
    # specifically wants the TradingView bottom-left special/custom range selector.
    opened = False
    open_errors = []
    coordinate_points = [
        (250, TV_VIEWPORT_HEIGHT - 34),
        (320, TV_VIEWPORT_HEIGHT - 34),
        (410, TV_VIEWPORT_HEIGHT - 34),
        (520, TV_VIEWPORT_HEIGHT - 34),
    ]
    for x, y in coordinate_points:
        try:
            await page.mouse.click(x, y)
            await page.wait_for_timeout(650)
            opened = True
            add("open_range_menu", True, f"coordinate={x},{y}")
            break
        except Exception as e:
            open_errors.append(f"coord_{x}_{y}:{type(e).__name__}")

    if not opened:
        candidates = [
            "button[aria-label*='Date Range' i]", "button[aria-label*='Tarih' i]", "button[aria-label*='Takvim' i]",
            "button[aria-label*='Go to' i]", "button[aria-label*='Git' i]",
            "[data-name*='date' i]", "[data-name*='range' i]", "[data-name*='go-to-date' i]",
            "button:has-text('1G')", "button:has-text('1D')", "span:has-text('1G')", "span:has-text('1D')",
        ]
        for sel in candidates:
            try:
                loc = page.locator(sel).last
                if await loc.is_visible(timeout=350):
                    await loc.click(timeout=600)
                    await page.wait_for_timeout(650)
                    opened = True
                    add("open_range_menu", True, f"selector={sel}")
                    break
            except Exception as e:
                open_errors.append(f"{sel}:{type(e).__name__}")

    if not opened:
        add("open_range_menu", False, ";".join(open_errors[:5]))
        return " | ".join(notes)

    # 2) Choose Custom Range / Special Range.
    clicked_custom = False
    custom_texts = ["Özel aralık", "Ozel aralik", "Özel aralığı", "Custom range", "Custom Range", "Özel", "Custom"]
    for txt in custom_texts:
        try:
            await page.get_by_text(txt, exact=False).first.click(timeout=750)
            await page.wait_for_timeout(500)
            clicked_custom = True
            add("choose_custom_range", True, f"text={txt}")
            break
        except Exception:
            pass
    if not clicked_custom:
        # Some locales open the date input directly; don't fail yet.
        add("choose_custom_range", False, "custom_text_not_found; will_try_visible_inputs_anyway")

    # 3) Fill start/end inputs. TradingView locale changes between combined
    # datetime fields and split date/time fields. Try split 4-input fill first,
    # then combined 2-input fill. The range is considered usable only if we can
    # write both target start and target end.
    def _date_formats(dt):
        return [dt.strftime("%d.%m.%Y"), dt.strftime("%Y-%m-%d"), dt.strftime("%d/%m/%Y"), dt.strftime("%m/%d/%Y")]

    def _time_formats(dt):
        return [dt.strftime("%H:%M")]

    format_pairs = [
        (window["start"].strftime("%d.%m.%Y %H:%M"), window["end"].strftime("%d.%m.%Y %H:%M")),
        (window["start"].strftime("%Y-%m-%d %H:%M"), window["end"].strftime("%Y-%m-%d %H:%M")),
        (window["start"].strftime("%d/%m/%Y %H:%M"), window["end"].strftime("%d/%m/%Y %H:%M")),
        (window["start"].strftime("%m/%d/%Y %H:%M"), window["end"].strftime("%m/%d/%Y %H:%M")),
    ]
    filled = False
    input_count = 0
    try:
        inputs = page.locator("input")
        input_count = await inputs.count()
        count = min(input_count, 12)

        async def write_input(index: int, value: str):
            inp = inputs.nth(index)
            await inp.click(timeout=650)
            await page.keyboard.press("Control+A")
            await page.keyboard.press("Backspace")
            await page.keyboard.type(value, delay=10)
            await page.wait_for_timeout(80)

        # Split date/time UI: date, time, date, time (or similar).
        if count >= 4:
            for sd in _date_formats(window["start"]):
                for ed in _date_formats(window["end"]):
                    try:
                        visible = []
                        for i in range(count):
                            try:
                                if await inputs.nth(i).is_visible(timeout=180):
                                    visible.append(i)
                            except Exception:
                                pass
                        if len(visible) >= 4:
                            vals = [sd, _time_formats(window["start"])[0], ed, _time_formats(window["end"])[0]]
                            for idx, val in zip(visible[:4], vals):
                                await write_input(idx, val)
                            filled = True
                            add("fill_start_end", True, f"split4 start={sd} {_time_formats(window['start'])[0]} end={ed} {_time_formats(window['end'])[0]}; input_count={input_count}")
                            break
                    except Exception:
                        pass
                if filled:
                    break

        # Combined datetime UI: start datetime, end datetime.
        if not filled and count >= 2:
            for start_val, end_val in format_pairs:
                try:
                    visible = []
                    for i in range(count):
                        try:
                            if await inputs.nth(i).is_visible(timeout=180):
                                visible.append(i)
                        except Exception:
                            pass
                    if len(visible) >= 2:
                        await write_input(visible[0], start_val)
                        await write_input(visible[1], end_val)
                        filled = True
                        add("fill_start_end", True, f"combined start={start_val} end={end_val}; input_count={input_count}")
                        break
                except Exception:
                    pass
    except Exception as e:
        add("fill_start_end", False, f"{type(e).__name__}: {e}")
    if not filled:
        add("fill_start_end", False, f"input_count={input_count}")

    # 4) Apply.
    clicked_apply = False
    for txt in ["Uygula", "Tamam", "Apply", "OK", "Done", "Git", "Go"]:
        try:
            await page.get_by_text(txt, exact=False).last.click(timeout=650)
            clicked_apply = True
            add("apply_range", True, f"text={txt}")
            break
        except Exception:
            pass
    if not clicked_apply:
        try:
            await page.keyboard.press("Enter")
            clicked_apply = True
            add("apply_range", True, "keyboard_enter")
        except Exception as e:
            add("apply_range", False, f"{type(e).__name__}: {e}")

    # 5) Give TradingView a very short reload budget. Browserless free sessions are short;
    # if this doesn't apply quickly, the screenshot step should continue and report failure.
    try:
        await page.wait_for_timeout(1800)
        add("reload_wait", True, "waited=1800ms")
    except Exception as e:
        add("reload_wait", False, f"{type(e).__name__}: {e}")

    return " | ".join(notes)

async def detect_latest_candle_point_from_page(page: Page) -> Optional[tuple[int, int, str]]:
    """Find the rightmost visible red/green candle body/wick from a temporary screenshot.

    Returns a point a little above that candle column. This is much more reliable
    than a fixed x-ratio when TradingView leaves future whitespace on the right.
    """
    if not TV_IMAGE_DETECT_LAST_CANDLE:
        return None
    temp = SCREENSHOT_DIR / f"_hover_probe_{uuid.uuid4().hex[:8]}.jpg"
    try:
        await page.screenshot(path=str(temp), full_page=False, type="jpeg", quality=62, timeout=5000)
        img = Image.open(temp).convert("RGB")
        w, h = img.size
        # Exclude top toolbar and volume pane. Use main candle plot area only.
        x0 = int(w * 0.035)
        x1 = int(w * min(0.985, CHART_CLIP_WIDTH_RATIO if CHART_ONLY_SCREENSHOT else 0.985))
        y0 = int(h * 0.08)
        y1 = int(h * 0.72)
        rightmost = []
        # Identify TradingView candle colors: teal/green and red/pink vertical pixels.
        for y in range(y0, y1, 2):
            for x in range(x0, x1, 2):
                r, g, b = img.getpixel((x, y))
                is_green = (g > r + 25 and g > b + 5 and g > 90 and r < 170)
                is_red = (r > g + 25 and r > b + 15 and r > 120 and g < 190)
                if is_green or is_red:
                    rightmost.append((x, y))
        if not rightmost:
            return None
        max_x = max(x for x, _ in rightmost)
        # Group pixels close to the rightmost candle column.
        cluster = [(x, y) for x, y in rightmost if abs(x - max_x) <= 12]
        if not cluster:
            cluster = [(x, y) for x, y in rightmost if abs(x - max_x) <= 24]
        min_y = min(y for _, y in cluster)
        hover_x = max(60, min(max_x, w - 80))
        hover_y = max(int(h * 0.12), min_y - 26)  # one tick above, not on candle body
        return hover_x, hover_y, f"image-detected latest candle column x={hover_x}, y={hover_y}"
    except Exception:
        return None
    finally:
        try:
            if temp.exists():
                temp.unlink()
        except Exception:
            pass

async def apply_session_view_controls(page: Page, view: str, target_date: Optional[str] = None):
    """Try to force TradingView to fit one full session/day on screen.

    The reliable public-control path is the bottom range button (Turkish: 1G, English: 1D).
    Exact historical date navigation is best-effort because public TradingView URLs do not
    consistently honor a direct date parameter in headless/browserless sessions.
    """
    if view not in {"session", "full_day", "day"} and not target_date:
        return
    # Click range buttons if visible. This is intentionally soft: failures should not break capture.
    candidates = [
        "button:has-text('1G')", "button:has-text('1D')",
        "div:has-text('1G')", "div:has-text('1D')",
        "span:has-text('1G')", "span:has-text('1D')",
    ]
    for sel in candidates:
        try:
            await page.locator(sel).last.click(timeout=700)
            await page.wait_for_timeout(1300)
            break
        except Exception:
            pass
    # Try the site's own custom range selector first: current = 09:45 -> now+1m (max 18:10),
    # target_date = 09:45 -> 18:10. This is best-effort because TradingView changes UI selectors.
    try:
        custom_note = await asyncio.wait_for(try_tradingview_custom_date_range(page, target_date, view), timeout=TV_CUSTOM_RANGE_MAX_SECONDS)
        setattr(page, "_bist_custom_range_note", custom_note)
    except asyncio.TimeoutError:
        custom_note = f"custom range core attempt timeboxed at {TV_CUSTOM_RANGE_MAX_SECONDS}s"
        setattr(page, "_bist_custom_range_note", custom_note)
    except Exception as e:
        custom_note = f"custom range core attempt failed: {type(e).__name__}: {e}"
        setattr(page, "_bist_custom_range_note", custom_note)
    # TradingView range=1D often means "last 24h", which can show the previous session too.
    # For BIST intraday analysis the user needs the latest regular session (open->close)
    # readable, not two days compressed. Zoom around the right side of the chart so the
    # newest session expands while the right info panel remains visible.
    try:
        await page.keyboard.press("End")
        await page.wait_for_timeout(250)
    except Exception:
        pass
    try:
        x = int(TV_VIEWPORT_WIDTH * SESSION_ZOOM_X_RATIO)
        y = int(TV_VIEWPORT_HEIGHT * SESSION_ZOOM_Y_RATIO)
        await page.mouse.move(x, y)
        for _ in range(max(0, SESSION_ZOOM_STEPS)):
            await page.mouse.wheel(0, SESSION_ZOOM_WHEEL_DELTA)
            await page.wait_for_timeout(220)
        await page.wait_for_timeout(700)
    except Exception:
        pass


async def try_tradingview_fullscreen(page: Page):
    """Best-effort TradingView fullscreen/expand action.

    This is intentionally soft: if TradingView refuses the click/shortcut in a
    headless Browserless session, capture continues. The goal is to maximize the
    chart canvas, not to accept any non-chart fallback.
    """
    if not TV_FORCE_FULLSCREEN:
        return
    selectors = [
        "button[data-name='fullscreen-button']",
        "button[aria-label*='Full screen' i]",
        "button[aria-label*='Fullscreen' i]",
        "button[aria-label*='Tam ekran' i]",
        "div[data-name='fullscreen-button']",
        "[data-name='header-toolbar-fullscreen']",
    ]
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if await loc.is_visible(timeout=500):
                await loc.click(timeout=700)
                await page.wait_for_timeout(1000)
                return
        except Exception:
            pass
    # Keyboard fallback. TradingView commonly supports a fullscreen/expand shortcut.
    try:
        await page.keyboard.press(TV_FULLSCREEN_SHORTCUT)
        await page.wait_for_timeout(1000)
    except Exception:
        pass

async def hover_latest_candle_column(page: Page):
    """Place the crosshair one tick above the latest visible candle column.

    Important: the user wants the crosshair/legend to reflect the final candle,
    but not by clicking directly on the candle body. We therefore try a small
    cluster of points close to the right price area, slightly above the candle
    body zone. This updates TradingView's top OHLC/volume legend while avoiding
    accidental drawing/selection.
    """
    if not TV_HOVER_LAST_CANDLE:
        return
    try:
        detected = await detect_latest_candle_point_from_page(page)
        if detected:
            dx, dy, _note = detected
            await page.mouse.move(dx, dy)
            await page.wait_for_timeout(220)
            if TV_CLICK_LAST_CANDLE_COLUMN:
                await page.mouse.click(dx, dy)
                await page.wait_for_timeout(260)
            await page.mouse.move(dx, dy)
            await page.wait_for_timeout(520)
            return

        right_edge = max(900, int(TV_VIEWPORT_WIDTH * CHART_CLIP_WIDTH_RATIO)) if CHART_ONLY_SCREENSHOT else TV_VIEWPORT_WIDTH
        left_crop = int(right_edge * SESSION_LEFT_CROP_RATIO) if (CHART_ONLY_SCREENSHOT and SESSION_LEFT_CROP_RATIO > 0) else 0
        left_crop = max(0, min(left_crop, right_edge - 850)) if CHART_ONLY_SCREENSHOT else 0
        capture_width = max(800, right_edge - left_crop) if CHART_ONLY_SCREENSHOT else TV_VIEWPORT_WIDTH

        # Primary point: near the final visible candle column, above the body.
        base_x = int(left_crop + capture_width * TV_LAST_CANDLE_X_RATIO)
        base_y = int(TV_VIEWPORT_HEIGHT * TV_LAST_CANDLE_Y_RATIO)
        # Try a tiny horizontal cluster because TradingView may leave right-side future whitespace.
        candidate_xs = [base_x, int(left_crop + capture_width * 0.945), int(left_crop + capture_width * 0.925)]
        candidate_y = base_y
        for x in candidate_xs:
            x = max(left_crop + 50, min(x, left_crop + capture_width - 80))
            await page.mouse.move(x, candidate_y)
            await page.wait_for_timeout(180)
            if TV_CLICK_LAST_CANDLE_COLUMN:
                await page.mouse.click(x, candidate_y)
                await page.wait_for_timeout(220)
            await page.mouse.move(x, candidate_y)
            await page.wait_for_timeout(180)
        # Finish on the primary point.
        await page.mouse.move(max(left_crop + 50, min(base_x, left_crop + capture_width - 80)), candidate_y)
        await page.wait_for_timeout(350)
    except Exception:
        pass

async def page_has_tradingview_symbol_error(page: Page) -> tuple[bool, str]:
    """Detect TradingView pages/widgets that loaded UI but not the requested chart.
    This prevents returning screenshots of "symbol unavailable" / loading / notification screens.
    """
    error_patterns = [
        "Sembol mevcut degil", "Sembol mevcut değil",
        "Sembol sadece", "TradingView'de bulunabilir", "TradingView’de bulunabilir",
        "Symbol is only available", "Symbol not available", "symbol is not available",
        "Invalid symbol", "No data here", "Try another symbol",
        "Analiziniz icin baska", "Analiziniz için başka",
        "Sembolu degistir", "Sembolü değiştir",
    ]
    try:
        body_text = await page.locator("body").inner_text(timeout=1200)
        body_text = repair_mojibake(body_text)
        body_text_ascii = to_ascii_tr(body_text)
        for pat in error_patterns:
            if pat.lower() in body_text.lower() or to_ascii_tr(pat).lower() in body_text_ascii.lower():
                return True, f"TradingView symbol/error message detected: {to_ascii_tr(pat)}"
    except Exception:
        pass
    # Modal text can be rendered in nested components; check common visible text selectors too.
    for pat in error_patterns[:8]:
        try:
            if await page.get_by_text(pat, exact=False).first.is_visible(timeout=300):
                return True, f"TradingView visible error detected: {to_ascii_tr(pat)}"
        except Exception:
            pass
    return False, ""


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
    # Wide chart screenshot. Default v4.2 does NOT square-crop or left-crop; it keeps a landscape
    # full chart canvas so candle proportions stay natural. CHART_CLIP_WIDTH_RATIO /
    # SESSION_LEFT_CROP_RATIO remain tunable env knobs, but defaults preserve full width.
    clip = None
    if CHART_ONLY_SCREENSHOT:
        # First remove the right TradingView sidebar, then crop a tunable part of the
        # left side where previous-session candles often remain. This keeps the latest
        # BIST session readable while preserving the price scale on the right edge.
        right_edge = max(900, int(TV_VIEWPORT_WIDTH * CHART_CLIP_WIDTH_RATIO))
        left_crop = int(right_edge * SESSION_LEFT_CROP_RATIO) if SESSION_LEFT_CROP_RATIO > 0 else 0
        left_crop = max(0, min(left_crop, right_edge - 850))
        clip = {
            "x": left_crop,
            "y": 0,
            "width": max(800, right_edge - left_crop),
            "height": max(600, int(TV_VIEWPORT_HEIGHT * CHART_CLIP_HEIGHT_RATIO)),
        }
    if img_type == "jpeg":
        await page.screenshot(path=str(out_path), full_page=False, type="jpeg", quality=quality, timeout=7000, clip=clip)
    else:
        await page.screenshot(path=str(out_path), full_page=False, type="png", timeout=14000, clip=clip)
    return screenshot_has_chart_content(out_path)

async def _screenshot_single_url(url: str, symbol: str, interval: str, mode: str, source_kind: str, view: str = "session", target_date: Optional[str] = None) -> tuple[Optional[Path], Optional[str], str, str]:
    img_type = "jpeg" if mode in {"current", "fast", "safe_current"} else "png"
    ext = "jpg" if img_type == "jpeg" else "png"
    filename = f"{symbol}_{interval}_{source_kind}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{uuid.uuid4().hex[:8]}.{ext}"
    out_path = SCREENSHOT_DIR / filename
    ctx = await BROWSER.get_context()
    page = None
    try:
        try:
            page = await ctx.new_page()
        except Exception as first_page_error:
            # Browserless free sessions can close the context after a timebox.
            # Reset once and reopen so custom-range remains a core path instead of poisoning later requests.
            if "closed" in str(first_page_error).lower() or "target" in str(first_page_error).lower():
                await BROWSER.reset()
                ctx = await BROWSER.get_context()
                page = await ctx.new_page()
            else:
                raise
        await install_fast_routes(page)
        page.set_default_timeout(8000 if mode == "safe_current" else (4500 if mode in {"current", "fast"} else 12000))
        # v5.7: range-first/no-prewait. Full TradingView can spend the whole Browserless
        # free-session budget just waiting for DOM/canvas. For session charts, stop waiting
        # early, then immediately try the custom range UI. A partially loaded page is still
        # useful if the bottom range control exists.
        nav_timeout = 45000 if mode == "safe_current" else (28000 if mode in {"current", "fast"} else 55000)
        if source_kind == "full" and mode in {"current", "fast"} and view in {"session", "full_day", "day"}:
            nav_timeout = int(os.getenv("TV_RANGE_FIRST_GOTO_TIMEOUT_MS", "8000"))
        page.set_default_navigation_timeout(nav_timeout)
        goto_note = ""
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=nav_timeout)
            goto_note = f"goto ok timeout_ms={nav_timeout}"
        except Exception as goto_error:
            # Continue: TradingView may still have enough DOM for range controls after a nav timeout.
            goto_note = f"goto soft-failed {type(goto_error).__name__}: {str(goto_error)[:160]}"
        setattr(page, "_bist_goto_note", goto_note)
        await click_soft_popups(page)
        # v5.8: for graph-only session requests, do not spend the Browserless free-session
        # budget on pre-fitting/zooming before the custom range target is attempted.
        # Go straight to the special range UI, log stages, then validate/screenshot once.
        if source_kind == "full" and mode in {"current", "fast"} and view in {"session", "full_day", "day"}:
            try:
                custom_note = await asyncio.wait_for(
                    try_tradingview_custom_date_range(page, target_date, view),
                    timeout=TV_CUSTOM_RANGE_MAX_SECONDS,
                )
            except asyncio.TimeoutError:
                custom_note = f"range_attempt enabled=true stage=custom_range_timeboxed max_seconds={TV_CUSTOM_RANGE_MAX_SECONDS}"
            except Exception as e:
                custom_note = f"range_attempt enabled=true stage=custom_range_failed error={type(e).__name__}: {e}"
            setattr(page, "_bist_custom_range_note", custom_note)
        else:
            await apply_session_view_controls(page, view, target_date)
        await try_tradingview_fullscreen(page)
        await hover_latest_candle_column(page)
        base_wait = (2200 if mode == "safe_current" else TV_WAIT_CURRENT_MS) if mode in {"current", "fast", "safe_current"} else TV_WAIT_BALANCED_MS
        canvas_wait = (1500 if mode == "safe_current" else TV_CANVAS_WAIT_CURRENT_MS) if mode in {"current", "fast", "safe_current"} else TV_CANVAS_WAIT_BALANCED_MS
        if source_kind == "full" and mode in {"current", "fast"} and view in {"session", "full_day", "day"}:
            canvas_wait = min(canvas_wait, 500)
        max_attempts = 1 if (source_kind == "full" and mode in {"current", "fast"} and view in {"session", "full_day", "day"}) else (5 if mode == "safe_current" else (2 if mode in {"current", "fast"} else 5))
        last_validation_note = ""
        for attempt in range(1, max_attempts + 1):
            await page.wait_for_timeout(650 if (source_kind == "full" and mode in {"current", "fast"} and view in {"session", "full_day", "day"}) else (base_wait if attempt == 1 else (2200 if mode == "safe_current" else (1400 if mode in {"current", "fast"} else 3500))))
            canvas_found = False
            for selector in ["canvas", "div.chart-container", "div.tv-lightweight-charts", "div[data-name='legend-source-item']", "div[data-name='legend']"]:
                try:
                    await page.locator(selector).first.wait_for(state="visible", timeout=canvas_wait)
                    canvas_found = True
                    break
                except Exception:
                    pass
            try:
                tv_error, tv_error_note = await page_has_tradingview_symbol_error(page)
                if tv_error:
                    last_validation_note = f"attempt {attempt}: {tv_error_note}"
                    # Do not keep this screenshot/candidate; continue to next TradingView path.
                    break
                await hover_latest_candle_column(page)
                verified_image = await capture_and_validate(page, out_path, img_type, 78 if img_type == "jpeg" else 0)
                if verified_image:
                    # Re-check after screenshot; some widgets show an error modal after canvas boot.
                    tv_error, tv_error_note = await page_has_tradingview_symbol_error(page)
                    if tv_error:
                        last_validation_note = f"attempt {attempt}: rejected after screenshot: {tv_error_note}"
                        break
                    status = "ok" if canvas_found else "ok_visual_verified"
                    range_note = getattr(page, "_bist_custom_range_note", "range_attempt note_missing")
                    goto_note = getattr(page, "_bist_goto_note", "goto note_missing")
                    note = f"TradingView {source_kind} screenshot captured and visual content check passed; no symbol/error overlay detected. | {goto_note} | {range_note}"
                    return out_path, f"/screenshots/{filename}", status, note
                last_validation_note = f"attempt {attempt}: image looked blank/loading"
            except Exception as shot_error:
                last_validation_note = f"attempt {attempt}: screenshot error {type(shot_error).__name__}: {shot_error}"
        try:
            if out_path.exists():
                out_path.unlink()
        except Exception:
            pass
        range_note = getattr(page, "_bist_custom_range_note", "range_attempt note_missing")
        goto_note = getattr(page, "_bist_goto_note", "goto note_missing")
        return None, None, "chart_loading_not_captured", f"TradingView {source_kind} did not pass validation; blank/loading/symbol-error image was rejected. {last_validation_note} | {goto_note} | {range_note}"
    except Exception as e:
        try:
            if out_path.exists():
                out_path.unlink()
        except Exception:
            pass
        range_note = getattr(page, "_bist_custom_range_note", "range_attempt note_missing") if page else "range_attempt page_not_created"
        goto_note = getattr(page, "_bist_goto_note", "goto note_missing") if page else "goto page_not_created"
        return None, None, "chart_failed_data_only", f"TradingView {source_kind} screenshot failed. Error: {type(e).__name__}: {e} | {goto_note} | {range_note}"
    finally:
        try:
            if page:
                await page.close()
        except Exception:
            pass

async def _screenshot_public_visual_fallback(symbol: str, interval: str, mode: str) -> tuple[Optional[Path], Optional[str], str, str]:
    """Last-resort visual fallback when TradingView cannot render in headless Render.
    It is not a candle-chart guarantee; it gives GPT a visual market page only when it passes a non-loading check.
    """
    img_type = "jpeg"
    ext = "jpg"
    ctx = await BROWSER.get_context()
    candidates = [
        ("midas_page", make_midas_url(symbol)),
        ("bloomberg_page", make_bloomberg_url(symbol)),
    ]
    notes = []
    for source_kind, page_url in candidates:
        filename = f"{symbol}_{interval}_{source_kind}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{uuid.uuid4().hex[:8]}.{ext}"
        out_path = SCREENSHOT_DIR / filename
        page = None
        try:
            page = await ctx.new_page()
            await install_fast_routes(page)
            page.set_default_timeout(4000)
            page.set_default_navigation_timeout(12000)
            await page.goto(page_url, wait_until="domcontentloaded", timeout=12000)
            await click_soft_popups(page)
            await page.wait_for_timeout(2200)
            await page.screenshot(path=str(out_path), full_page=False, type="jpeg", quality=76, timeout=5000)
            # Use a lighter check: public pages are not pure chart canvases, but reject blank/loading white pages.
            if screenshot_has_chart_content(out_path):
                return out_path, f"/screenshots/{filename}", "ok_public_visual_fallback", f"TradingView did not render in time; public visual fallback captured from {source_kind}. Use this only as fallback visual context, not as a guaranteed TradingView candle chart."
            notes.append(f"{source_kind}: visual validation failed")
            try:
                if out_path.exists():
                    out_path.unlink()
            except Exception:
                pass
        except Exception as e:
            notes.append(f"{source_kind}: {type(e).__name__}: {e}")
            try:
                if out_path.exists():
                    out_path.unlink()
            except Exception:
                pass
        finally:
            try:
                if page:
                    await page.close()
            except Exception:
                pass
    return None, None, "chart_timeboxed_no_image", "TradingView failed and public visual fallback also failed/rejected. " + " | ".join(notes)

async def screenshot_tradingview(url: str, symbol: str, interval: str, mode: str = "current", view: str = "session", target_date: Optional[str] = None) -> tuple[Optional[Path], Optional[str], str, str]:
    """Strict TradingView-only capture.
    Goal: return the exact requested TradingView chart image, not a public quote page.
    Order:
      1) Local minimal TradingView Advanced Chart Widget HTML
      2) Official TradingView widgetembed URL
      3) Full TradingView /chart URL
    It never returns loading/blank images and never returns Midas/Bloomberg as chart.
    """
    hard_timeout = TV_SAFE_CURRENT_HARD_TIMEOUT_SECONDS if mode == "safe_current" else (TV_CURRENT_HARD_TIMEOUT_SECONDS if mode in {"current", "fast"} else TV_BALANCED_HARD_TIMEOUT_SECONDS)

    async def _try_with_budget(coro, seconds: int, timeout_status: str, timeout_note: str):
        try:
            return await asyncio.wait_for(coro, timeout=seconds)
        except asyncio.TimeoutError:
            return None, None, timeout_status, timeout_note
        except Exception as e:
            return None, None, "chart_failed_data_only", f"{type(e).__name__}: {e}"

    async def _run():
        notes = []
        # 1) Local minimal TV widget HTML: fastest exact TradingView chart path.
        if mode in {"current", "fast", "safe_current"} and view not in {"session", "full_day", "day"}:
            local_budget = 24 if mode in {"current", "fast"} else 34
            local_url = make_tv_local_html(symbol, interval, view)
            out_path, shot_path, status, note = await _try_with_budget(
                _screenshot_single_url(local_url, symbol, interval, mode, "tvlocal", view, target_date),
                local_budget,
                "tvlocal_timeboxed",
                f"Local TradingView widget timeboxed at {local_budget}s."
            )
            notes.append(note)
            if out_path and shot_path:
                return out_path, shot_path, "ok_tradingview_local_widget", note + " | Exact TradingView chart path: local widget; session-zoom view attempts to show the latest BIST session open-to-close with readable 5m candles and chart area; external quote fields provide price/stat context."

        # 2) Official lightweight widgetembed.
        if mode in {"current", "fast", "safe_current"} and USE_WIDGET_FOR_CURRENT and view not in {"session", "full_day", "day"}:
            widget_budget = 22 if mode in {"current", "fast"} else 30
            widget_url = make_tv_widget_url(symbol, interval, view)
            out_path, shot_path, status, note = await _try_with_budget(
                _screenshot_single_url(widget_url, symbol, interval, mode, "widget", view, target_date),
                widget_budget,
                "widget_timeboxed",
                f"TradingView widgetembed timeboxed at {widget_budget}s."
            )
            notes.append(note)
            if out_path and shot_path:
                return out_path, shot_path, "ok_tradingview_widgetembed", note + " | Exact TradingView chart path: official widgetembed; session-zoom view attempts to show the latest BIST session open-to-close with readable 5m candles and chart area; external quote fields provide price/stat context."

        # 3) Full TradingView chart, most complete but heaviest.
        # v5.7: keep nearly all current-mode budget for the full-chart path, but make
        # its internal steps shorter. This lets range_attempt return its stage notes instead
        # of the wrapper killing it at 48s before debug can surface.
        full_budget = (int(os.getenv("TV_FULL_CHART_BUDGET_SECONDS", str(max(20, hard_timeout - 3)))) if (mode in {"current", "fast"} and view in {"session", "full_day", "day"}) else (34 if mode in {"current", "fast"} else (70 if mode == "safe_current" else hard_timeout)))
        out_path, shot_path, status, note = await _try_with_budget(
            _screenshot_single_url(url, symbol, interval, mode, "full", view, target_date),
            full_budget,
            "full_chart_timeboxed",
            f"Full TradingView chart timeboxed at {full_budget}s."
        )
        notes.append(note)
        if out_path and shot_path:
            return out_path, shot_path, "ok_tradingview_full_chart", " | ".join(notes + ["Exact TradingView chart path: full chart; session_tight_fit aggressively zooms the latest BIST session so the previous day is minimized, 5m candles are more readable, and the right-side watchlist/info panel is cropped out; external quote/stat context is intentionally not returned by this graph-only endpoint."])

        return None, None, "strict_tradingview_image_failed", " | ".join(notes + ["No verified TradingView chart image returned. No public quote-page fallback was used, because user requested the actual chart screenshot only."])

    try:
        return await asyncio.wait_for(_run(), timeout=hard_timeout)
    except asyncio.TimeoutError:
        return None, None, "strict_tradingview_timeboxed_no_image", f"Strict TradingView chart capture hard-timeboxed at {hard_timeout}s; no loading/blank screenshot was returned."
    except Exception as e:
        await BROWSER.reset()
        return None, None, "strict_tradingview_failed", f"Strict TradingView chart capture failed. Error: {type(e).__name__}: {e}"

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
        return [], "current_quote_only", f"BIST session target: {BIST_SESSION_START}-{BIST_SESSION_END}. Current mode: speed-first current chart; slow Yahoo/Stooq OHLC calls skipped. Price verification uses public quote layers. BIST session target is 09:55-18:10; do not claim exact full-day coverage unless the screenshot x-axis visually confirms this band. Last-candle crosshair target is enabled above the final candle column."
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


class PrepareChartResponse(BaseModel):
    ok: bool
    version: str
    session_id: Optional[str] = None
    status: str
    symbol: str
    interval: str
    target_date: Optional[str] = None
    target_start: str
    target_end: str
    tradingview_url: str
    range_attempt: dict = Field(default_factory=dict)
    expires_at_utc: Optional[str] = None
    note: str = ""

class CaptureChartResponse(BaseModel):
    ok: bool
    version: str
    session_id: str
    screenshot_url: Optional[str] = None
    chart_status: str
    range_attempt: dict = Field(default_factory=dict)
    note: str = ""
    captured_at_utc: str

async def _prepare_chart_internal(request: Request, symbol: str, interval: str, target_date: Optional[str], mode: str, view: str) -> dict:
    await cleanup_prepared_charts()
    clean_symbol = normalize_symbol(symbol)
    if interval not in TV_INTERVALS:
        raise HTTPException(status_code=400, detail=f"Gecersiz interval: {interval}. Destek: {', '.join(TV_INTERVALS.keys())}")
    if view not in {"session", "full_day", "day", "auto"}:
        raise HTTPException(status_code=400, detail="view session, full_day, day veya auto olmali.")
    if target_date and not re.match(r"^\d{4}-\d{2}-\d{2}$", target_date):
        raise HTTPException(status_code=400, detail="target_date YYYY-MM-DD formatinda olmali.")

    window = build_target_session_window(target_date)
    tv_url = make_tv_url(clean_symbol, interval, view, target_date)
    sid = uuid.uuid4().hex[:12]
    page = None
    stages_note = []
    status = "failed"
    try:
        page = await BROWSER.new_page("prepare")
        await install_fast_routes(page)
        page.set_default_timeout(7000)
        page.set_default_navigation_timeout(TV_PREPARE_GOTO_TIMEOUT_MS)
        try:
            await page.goto(tv_url, wait_until="domcontentloaded", timeout=TV_PREPARE_GOTO_TIMEOUT_MS)
            stages_note.append(f"goto ok timeout_ms={TV_PREPARE_GOTO_TIMEOUT_MS}")
        except Exception as e:
            # Soft fail: TradingView can still expose enough DOM after timeout.
            stages_note.append(f"goto soft-failed {type(e).__name__}: {str(e)[:160]}")
        await click_soft_popups(page)
        range_note = "range_attempt enabled=false"
        if view in {"session", "full_day", "day"}:
            try:
                range_note = await asyncio.wait_for(
                    try_tradingview_custom_date_range(page, target_date, view),
                    timeout=max(6, TV_CUSTOM_RANGE_MAX_SECONDS),
                )
            except asyncio.TimeoutError:
                range_note = f"range_attempt enabled=true stage=custom_range_timeboxed max_seconds={TV_CUSTOM_RANGE_MAX_SECONDS}"
            except Exception as e:
                range_note = f"range_attempt enabled=true stage=custom_range_failed error={type(e).__name__}: {str(e)[:160]}"
        stages_note.append(range_note)
        # Exact visual-only mode: do not continue to capture if the requested
        # 09:55-18:10 custom range was not demonstrably applied. This prevents
        # returning misleading multi-day TradingView screenshots.
        if TV_REQUIRE_EXACT_RANGE and view in {"session", "full_day", "day"} and not range_note_has_success(range_note):
            note = " | ".join(stages_note + ["stage=exact_range_required ok=false detail=custom_range_not_confirmed"])
            range_attempt = build_range_attempt_summary(target_date, view, "prepare_failed_exact_range_not_confirmed", note)
            range_attempt["stages"] = _stage_list_from_note(note)
            try:
                await page.close()
            except Exception:
                pass
            return {
                "ok": False,
                "version": APP_VERSION,
                "session_id": None,
                "status": "prepare_failed_exact_range_not_confirmed",
                "symbol": clean_symbol,
                "interval": interval,
                "target_date": target_date,
                "target_start": window["start_label"],
                "target_end": window["end_label"],
                "tradingview_url": tv_url,
                "range_attempt": range_attempt,
                "expires_at_utc": None,
                "note": to_ascii_tr("Exact custom range could not be confirmed. No screenshot will be returned because wrong-date/multi-day charts are forbidden. " + note),
            }
        try:
            await page.wait_for_timeout(TV_PREPARE_POST_RANGE_WAIT_MS)
        except Exception:
            pass
        try:
            await try_tradingview_fullscreen(page)
        except Exception as e:
            stages_note.append(f"stage=fullscreen ok=false detail={type(e).__name__}")
        try:
            await hover_latest_candle_column(page)
            stages_note.append("stage=hover_last_candle ok=true")
        except Exception as e:
            stages_note.append(f"stage=hover_last_candle ok=false detail={type(e).__name__}")

        expires_at = time.time() + PREPARE_SESSION_TTL_SECONDS
        PREPARED_CHARTS[sid] = {
            "page": page,
            "symbol": clean_symbol,
            "interval": interval,
            "target_date": target_date,
            "view": view,
            "url": tv_url,
            "created_at": time.time(),
            "expires_at": expires_at,
            "range_note": " | ".join(stages_note),
            "window": window,
        }
        page = None  # ownership transferred to session store
        status = "ready_for_capture"
        note = " | ".join(stages_note)
        range_attempt = build_range_attempt_summary(target_date, view, status, note)
        range_attempt["stages"] = _stage_list_from_note(note)
        return {
            "ok": True,
            "version": APP_VERSION,
            "session_id": sid,
            "status": status,
            "symbol": clean_symbol,
            "interval": interval,
            "target_date": target_date,
            "target_start": window["start_label"],
            "target_end": window["end_label"],
            "tradingview_url": tv_url,
            "range_attempt": range_attempt,
            "expires_at_utc": datetime.fromtimestamp(expires_at, timezone.utc).isoformat(),
            "note": to_ascii_tr("Prepare finished; call /capture-chart quickly. " + note),
        }
    except Exception as e:
        if page:
            try:
                await page.close()
            except Exception:
                pass
        note = " | ".join(stages_note + [f"prepare failed {type(e).__name__}: {str(e)[:200]}"])
        range_attempt = build_range_attempt_summary(target_date, view, "prepare_failed", note)
        range_attempt["stages"] = _stage_list_from_note(note)
        return {
            "ok": False,
            "version": APP_VERSION,
            "session_id": None,
            "status": "prepare_failed",
            "symbol": clean_symbol if 'clean_symbol' in locals() else symbol,
            "interval": interval,
            "target_date": target_date,
            "target_start": window["start_label"] if 'window' in locals() else "",
            "target_end": window["end_label"] if 'window' in locals() else "",
            "tradingview_url": tv_url if 'tv_url' in locals() else "",
            "range_attempt": range_attempt,
            "expires_at_utc": None,
            "note": to_ascii_tr(note),
        }

async def _capture_chart_internal(request: Request, session_id: str, close_after: bool = True, include_base64: bool = False) -> dict:
    await cleanup_prepared_charts()
    rec = PREPARED_CHARTS.get(session_id)
    if not rec:
        return {
            "ok": False,
            "version": APP_VERSION,
            "session_id": session_id,
            "screenshot_url": None,
            "chart_status": "session_not_found_or_expired",
            "range_attempt": {},
            "note": "Prepared chart session not found or expired. Call /prepare-chart again and capture quickly.",
            "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        }
    page = rec.get("page")
    clean_symbol = rec.get("symbol", "SYMBOL")
    interval = rec.get("interval", "5m")
    target_date = rec.get("target_date")
    view = rec.get("view", "session")
    note_parts = [rec.get("range_note", "")]
    img_type = "jpeg"
    ext = "jpg"
    filename = f"{clean_symbol}_{interval}_prepared_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{uuid.uuid4().hex[:8]}.{ext}"
    out_path = SCREENSHOT_DIR / filename
    shot_path = f"/screenshots/{filename}"
    screenshot_url = None
    chart_status = "capture_failed"
    try:
        if not page:
            raise RuntimeError("prepared page missing")
        try:
            await click_soft_popups(page)
        except Exception:
            pass
        try:
            await hover_latest_candle_column(page)
            note_parts.append("stage=capture_hover_last_candle ok=true")
        except Exception as e:
            note_parts.append(f"stage=capture_hover_last_candle ok=false detail={type(e).__name__}")
        ok_img = await capture_and_validate(page, out_path, img_type, 84)
        if ok_img:
            tv_error, tv_error_note = await page_has_tradingview_symbol_error(page)
            if tv_error:
                chart_status = "rejected_symbol_error"
                note_parts.append(tv_error_note)
                try: out_path.unlink()
                except Exception: pass
                screenshot_url = None
            else:
                chart_status = "ok_prepared_capture"
                screenshot_url = absolute_url(request, shot_path)
                note_parts.append("stage=final_screenshot ok=true")
        else:
            chart_status = "prepared_capture_failed_validation"
            note_parts.append("stage=final_screenshot ok=false detail=image_blank_loading_or_not_chart")
            try:
                if out_path.exists(): out_path.unlink()
            except Exception:
                pass
    except Exception as e:
        chart_status = "capture_exception"
        note_parts.append(f"stage=final_screenshot ok=false detail={type(e).__name__}: {str(e)[:180]}")
        try:
            if out_path.exists(): out_path.unlink()
        except Exception:
            pass
    finally:
        if close_after:
            PREPARED_CHARTS.pop(session_id, None)
            try:
                if page:
                    await page.close()
            except Exception:
                pass
    note = " | ".join([x for x in note_parts if x])
    range_attempt = build_range_attempt_summary(target_date, view, chart_status, note)
    range_attempt["stages"] = _stage_list_from_note(note)
    result = {
        "ok": bool(screenshot_url),
        "version": APP_VERSION,
        "session_id": session_id,
        "screenshot_url": screenshot_url,
        "chart_status": chart_status,
        "range_attempt": range_attempt,
        "note": to_ascii_tr(note),
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    if include_base64 and screenshot_url and out_path.exists():
        result["screenshot_base64_png"] = base64.b64encode(out_path.read_bytes()).decode("utf-8")
    return result

@app.get("/prepare-chart", response_model=PrepareChartResponse)
async def prepare_chart(
    request: Request,
    symbol: str = Query(..., description="BIST sembolu. Ornek: THYAO"),
    interval: str = Query("5m", description="Sabit hedef 5m; digerleri test icin."),
    target_date: Optional[str] = Query(None, description="YYYY-MM-DD; tarihli grafik icin."),
    mode: str = Query("current", description="current/fast/safe_current; prepare-capture modunda current onerilir."),
    view: str = Query("session", description="session hedefi: 09:55-18:10."),
):
    return await _prepare_chart_internal(request, symbol, interval, target_date, mode, view)

@app.get("/capture-chart", response_model=CaptureChartResponse)
async def capture_chart(
    request: Request,
    session_id: str = Query(..., description="prepare-chart sonucunda gelen session_id"),
    close_after: bool = Query(True, description="true ise screenshot sonrasi hazir sayfayi kapatir."),
    include_base64: bool = Query(False, description="true ise base64 de doner; genelde false."),
):
    return await _capture_chart_internal(request, session_id, close_after, include_base64)

@app.get("/prepared-sessions")
async def prepared_sessions():
    await cleanup_prepared_charts()
    return {
        "ok": True,
        "version": APP_VERSION,
        "count": len(PREPARED_CHARTS),
        "sessions": [
            {
                "session_id": sid,
                "symbol": rec.get("symbol"),
                "interval": rec.get("interval"),
                "target_date": rec.get("target_date"),
                "expires_at_utc": datetime.fromtimestamp(rec.get("expires_at", 0), timezone.utc).isoformat(),
                "range_note": to_ascii_tr(rec.get("range_note", ""))[:600],
            }
            for sid, rec in PREPARED_CHARTS.items()
        ],
    }

@app.get("/chart-agent")
async def chart_agent(
    request: Request,
    symbol: str = Query(...),
    interval: str = Query("5m"),
    target_date: Optional[str] = Query(None),
    mode: str = Query("current"),
    view: str = Query("session"),
):
    prep = await _prepare_chart_internal(request, symbol, interval, target_date, mode, view)
    if not prep.get("ok") or not prep.get("session_id"):
        return {"ok": False, "version": APP_VERSION, "phase": "prepare", "prepare": prep}
    cap = await _capture_chart_internal(request, prep["session_id"], close_after=True, include_base64=False)
    return {"ok": bool(cap.get("screenshot_url")), "version": APP_VERSION, "phase": "capture", "prepare": prep, "capture": cap}

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
    mode: str = Query("current", description="current, safe_current, fast veya balanced. current guncel grafik icin budgeted graph-first 65sn moddur; safe_current 90sn daha guvenlidir; balanced tarihsel/OHLC icin detaylidir."),
    auto_clear: bool = Query(True, description="true ise yeni grafik isteginden once eski screenshot dosyalarini siler."),
    view: str = Query("session", description="session/full_day/day: son BIST seansini zoom-fit yapar; 5dk mumlari daha okunur hale getirir; auto: eski davranis."),
):
    clean_symbol = normalize_symbol(symbol)
    if interval not in TV_INTERVALS:
        raise HTTPException(status_code=400, detail=f"Geçersiz interval: {interval}. Destek: {', '.join(TV_INTERVALS.keys())}")
    if mode not in {"current", "balanced", "fast", "safe_current"}:
        raise HTTPException(status_code=400, detail="mode current, safe_current, balanced veya fast olmalı.")
    if view not in {"session", "full_day", "day", "auto"}:
        raise HTTPException(status_code=400, detail="view session, full_day, day veya auto olmali.")
    if target_date and not re.match(r"^\d{4}-\d{2}-\d{2}$", target_date):
        raise HTTPException(status_code=400, detail="target_date YYYY-MM-DD formatında olmalı.")
    yahoo_symbol = make_yahoo_symbol(clean_symbol)
    tv_url = make_tv_url(clean_symbol, interval, view, target_date)

    clear_result = {"deleted": 0, "kept": 0}
    if auto_clear and AUTO_CLEAR_SCREENSHOTS:
        clear_result = clear_screenshot_files(keep_last=SCREENSHOT_KEEP_LAST)

    request_timeout = TOTAL_SAFE_CURRENT_HARD_TIMEOUT_SECONDS if mode == "safe_current" else (TOTAL_BALANCED_HARD_TIMEOUT_SECONDS if mode == "balanced" else TOTAL_CHART_HARD_TIMEOUT_SECONDS)
    # v5.5 GRAPH-ONLY MODE:
    # Do not call Yahoo/Stooq/Midas/Bloomberg/Borsa Istanbul here.
    # The only responsibility of this API is to return the correct TradingView chart image.
    # Market/news/quote verification must be handled by the GPT or another action.
    try:
        out_path, shot_path, chart_status, chart_note = await asyncio.wait_for(
            screenshot_tradingview(tv_url, clean_symbol, interval, mode, view, target_date),
            timeout=request_timeout,
        )
    except asyncio.TimeoutError:
        out_path, shot_path, chart_status, chart_note = None, None, "request_timeboxed_no_image", f"Request timeboxed at {request_timeout}s; no unverified image returned."

    records, data_status, data_note = [], "graph_only_no_market_data", "Browserless-key screen capture mode: PagePixels is disabled; external quote/news/data layers are skipped by this endpoint. The GPT should fetch current market/news information separately if needed."
    quote_snapshots, official_reference = [], {}

    screenshot_base64 = None
    screenshot_url = absolute_url(request, shot_path) if shot_path else None
    if include_base64 and out_path and out_path.exists():
        screenshot_base64 = base64.b64encode(out_path.read_bytes()).decode("utf-8")

    range_attempt = build_range_attempt_summary(target_date, view, chart_status, chart_note)

    final_note = to_ascii_tr(
        f"{chart_note} | Screenshot cleanup before capture: deleted={clear_result.get('deleted', 0)}, kept={clear_result.get('kept', 0)}. | {data_note} | Ucretsiz kaynaklarda BIST intraday verileri gecikmeli/sinirli/eksik olabilir. "
        "Mikro yapi, derinlik, AKD/BOFA ve karanlik oda icin araci kurum ekrani gerekir. "
        "This endpoint only verifies and returns the chart image. The GPT must fetch market/news/quote information with separate sources if needed."
    )

    return ChartResponse(
        symbol=clean_symbol,
        yahoo_symbol=yahoo_symbol,
        interval=interval,
        yahoo_interval_used=YF_INTERVALS.get(interval, "5m"),
        range_hint=range_hint,
        target_date=target_date,
        source_chart="TradingView visual chart screenshot via Browserless remote browser; graph-only range-first/no-prewait capture. Uses native custom range as core target (current 09:55→now+1m capped 18:10, historical 09:55→18:10) and image-detected last-candle hover above the final candle column",
        source_data="Browserless-key strict TradingView screen capture. PagePixels is disabled; no market-data calls are made by this endpoint.",
        tradingview_url=tv_url,
        screenshot_url=screenshot_url,
        screenshot_base64_png=screenshot_base64,
        chart_status=chart_status,
        range_attempt=range_attempt,
        ohlc_sample=records,
        ohlc_count=len(records),
        quote_snapshots=quote_snapshots,
        official_reference=official_reference,
        data_status=data_status,
        data_note=final_note,
        performance_note=(("browserless remote + " if BROWSERLESS_WS_ENDPOINT else "local browser + ") + ("safe_current mode: strict TradingView-only visual capture; local widget -> widgetembed -> full chart" if mode == "safe_current" else "current mode: strict TradingView-only visual capture; local widget -> widgetembed -> full chart") if mode in {"current", "fast", "safe_current"} else "balanced mode: strict TradingView + slower OHLC fallback enabled"),
        captured_at_utc=datetime.now(timezone.utc).isoformat(),
    )
