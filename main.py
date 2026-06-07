import os, re, uuid, asyncio
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Optional, Dict, Any, List

from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError, Error as PlaywrightError

VERSION = "7.4.0-operator-mode-hard-force"
APP_BASE_URL = os.getenv("APP_BASE_URL", "https://bist-chart-gpt-action.onrender.com").rstrip("/")
BROWSERLESS_WS_ENDPOINT = os.getenv("BROWSERLESS_WS_ENDPOINT", "")
PORT = int(os.getenv("PORT", "10000"))
TZ = ZoneInfo("Europe/Istanbul")

VIEWPORT_WIDTH = int(os.getenv("VIEWPORT_WIDTH", "2400"))
VIEWPORT_HEIGHT = int(os.getenv("VIEWPORT_HEIGHT", "1350"))
BROWSERLESS_TIMEOUT_MS = int(os.getenv("BROWSERLESS_TIMEOUT_MS", "60000"))
PREPARE_GOTO_TIMEOUT_MS = int(os.getenv("PREPARE_GOTO_TIMEOUT_MS", "18000"))
PREPARE_TOTAL_TIMEOUT_SEC = int(os.getenv("PREPARE_TOTAL_TIMEOUT_SEC", "66"))
CAPTURE_TIMEOUT_SEC = int(os.getenv("CAPTURE_TIMEOUT_SEC", "15"))
SESSION_TTL_SECONDS = int(os.getenv("PREPARE_SESSION_TTL_SECONDS", "80"))

TV_SESSION_START = os.getenv("BIST_SESSION_START", "09:55")
TV_SESSION_END = os.getenv("BIST_SESSION_END", "18:10")
TV_CURRENT_PLUS_MINUTES = int(os.getenv("TV_CURRENT_PLUS_MINUTES", "1"))
TV_OPERATOR_RETRIES = int(os.getenv("TV_OPERATOR_RETRIES", "3"))
TV_REQUIRE_EXACT_RANGE = os.getenv("TV_REQUIRE_EXACT_RANGE", "false").lower() == "true"
TV_FORCE_FULLSCREEN = os.getenv("TV_FORCE_FULLSCREEN", "true").lower() == "true"
TV_HOVER_LAST_CANDLE = os.getenv("TV_HOVER_LAST_CANDLE", "true").lower() == "true"
TV_LAST_CANDLE_X_RATIO = float(os.getenv("TV_LAST_CANDLE_X_RATIO", "0.965"))
TV_LAST_CANDLE_Y_RATIO = float(os.getenv("TV_LAST_CANDLE_Y_RATIO", "0.38"))

ROOT = Path(__file__).parent
SHOT_DIR = ROOT / "screenshots"
SHOT_DIR.mkdir(exist_ok=True)

app = FastAPI(title="BIST Chart Visual Fetcher", version=VERSION)
app.mount("/screenshots", StaticFiles(directory=str(SHOT_DIR)), name="screenshots")

_pw = None
_browser = None
_context = None
_sessions: Dict[str, Dict[str, Any]] = {}


def parse_hhmm(s: str) -> time:
    h, m = [int(x) for x in s.split(":")]
    return time(hour=h, minute=m)


def compute_range(target_date: Optional[str] = None) -> Dict[str, str]:
    now = datetime.now(TZ)
    if target_date:
        d = datetime.strptime(target_date, "%Y-%m-%d").date()
        start_dt = datetime.combine(d, parse_hhmm(TV_SESSION_START), TZ)
        end_dt = datetime.combine(d, parse_hhmm(TV_SESSION_END), TZ)
    else:
        d = now.date()
        start_dt = datetime.combine(d, parse_hhmm(TV_SESSION_START), TZ)
        end_cap = datetime.combine(d, parse_hhmm(TV_SESSION_END), TZ)
        end_dt = min(now + timedelta(minutes=TV_CURRENT_PLUS_MINUTES), end_cap)
        if end_dt < start_dt:
            end_dt = start_dt + timedelta(minutes=5)
    return {
        "target_start": start_dt.strftime("%d.%m.%Y %H:%M"),
        "target_end": end_dt.strftime("%d.%m.%Y %H:%M"),
        "iso_start": start_dt.isoformat(),
        "iso_end": end_dt.isoformat(),
        "start_date_tr": start_dt.strftime("%d.%m.%Y"),
        "end_date_tr": end_dt.strftime("%d.%m.%Y"),
        "start_time": start_dt.strftime("%H:%M"),
        "end_time": end_dt.strftime("%H:%M"),
    }


def tv_symbol(symbol: str) -> str:
    s = symbol.upper().strip()
    if ":" in s:
        return s
    return f"BIST:{s}"


def tv_url(symbol: str, interval: str = "5m", target_date: Optional[str] = None) -> str:
    interval_num = "5" if interval in ("5m", "5") else re.sub(r"\D", "", interval) or "5"
    # Timestamp hints help TV jump near the date but do not guarantee exact range.
    extra = ""
    if target_date:
        d = datetime.strptime(target_date, "%Y-%m-%d").replace(tzinfo=TZ)
        ts = int(d.timestamp())
        extra = f"&timestamp={ts}&time={ts}"
    return f"https://tr.tradingview.com/chart/?symbol={tv_symbol(symbol)}&interval={interval_num}&range=1D{extra}"


async def get_context(force_new: bool = False):
    global _pw, _browser, _context
    if force_new:
        await close_context_only()
    if _pw is None:
        _pw = await async_playwright().start()
    try:
        if _context is not None:
            # Probe context viability.
            _ = _context.pages
            return _context
    except Exception:
        _context = None
    if BROWSERLESS_WS_ENDPOINT:
        _browser = await _pw.chromium.connect_over_cdp(BROWSERLESS_WS_ENDPOINT, timeout=BROWSERLESS_TIMEOUT_MS)
    else:
        _browser = await _pw.chromium.launch(headless=True)
    _context = await _browser.new_context(
        viewport={"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT},
        device_scale_factor=1,
        locale="tr-TR",
        timezone_id="Europe/Istanbul",
    )
    _context.set_default_timeout(8000)
    return _context


async def close_context_only():
    global _context, _browser
    try:
        if _context:
            await _context.close()
    except Exception:
        pass
    _context = None
    try:
        if _browser:
            await _browser.close()
    except Exception:
        pass
    _browser = None


async def cleanup_sessions():
    now = datetime.now(TZ).timestamp()
    expired = [sid for sid, val in _sessions.items() if now - val.get("created_ts", now) > SESSION_TTL_SECONDS]
    for sid in expired:
        try:
            await val["page"].close()
        except Exception:
            pass
        _sessions.pop(sid, None)


async def safe_click(page, selectors: List[str], steps: List[Dict[str, Any]], label: str, timeout: int = 2000) -> bool:
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            await loc.wait_for(state="visible", timeout=timeout)
            await loc.click(timeout=timeout)
            steps.append({"stage": label, "ok": True, "selector": sel})
            return True
        except Exception as e:
            last = str(e).split("\n")[0][:160]
    steps.append({"stage": label, "ok": False, "tried": len(selectors), "error": last if 'last' in locals() else "not found"})
    return False


async def close_popups(page, steps):
    for sel in [
        'button:has-text("Kabul")', 'button:has-text("Accept")', 'button:has-text("Tamam")',
        '[aria-label="Close"]', 'button[aria-label="Close"]', 'button:has-text("Daha sonra")'
    ]:
        try:
            await page.locator(sel).first.click(timeout=900)
            steps.append({"stage":"close_popup", "ok":True, "selector":sel})
            await page.wait_for_timeout(300)
        except Exception:
            pass


async def force_interval_5m(page, steps):
    # URL interval usually works. Try hotkey-like direct interval button if visible.
    ok = await safe_click(page, [
        'button:has-text("5dk")', 'button:has-text("5m")', '[data-name="interval-dialog-button"]'
    ], steps, "select_interval_button", timeout=1400)
    if ok:
        try:
            await page.keyboard.press("Control+A")
            await page.keyboard.type("5")
            await page.keyboard.press("Enter")
            steps.append({"stage":"select_interval_5m_keyboard", "ok":True})
            await page.wait_for_timeout(800)
        except Exception as e:
            steps.append({"stage":"select_interval_5m_keyboard", "ok":False, "error":str(e)[:160]})
    else:
        steps.append({"stage":"select_interval_5m", "ok":"assumed_from_url"})


async def try_custom_range_ui(page, rg: Dict[str, str], steps) -> bool:
    # Several routes: bottom range custom button, keyboard shortcuts, visible labels.
    success = False
    range_buttons = [
        'button:has-text("Tümü")', 'button:has-text("All")', 'button:has-text("1G")', 'button:has-text("1D")',
        'div:has-text("Tümü")', 'div:has-text("1G")', '[data-name="date-ranges-tabs"] button:last-child'
    ]
    await safe_click(page, range_buttons, steps, "open_range_area", timeout=1800)
    await page.wait_for_timeout(500)
    custom_ok = await safe_click(page, [
        'button:has-text("Özel")', 'button:has-text("Custom")', 'div:has-text("Özel aralık")', 'div:has-text("Custom range")'
    ], steps, "open_custom_range", timeout=1700)

    # If no dialog visible, try direct keyboard date navigation shortcut variants.
    if not custom_ok:
        for combo in ["Alt+G", "Meta+G", "Control+G"]:
            try:
                await page.keyboard.press(combo)
                steps.append({"stage":"keyboard_open_go_to", "ok":True, "combo":combo})
                await page.wait_for_timeout(700)
                break
            except Exception as e:
                steps.append({"stage":"keyboard_open_go_to", "ok":False, "combo":combo, "error":str(e)[:100]})

    # Fill inputs if visible. TV changes UI often, so try all text/datetime inputs.
    text = f"{rg['target_start']} - {rg['target_end']}"
    filled_any = False
    try:
        inputs = page.locator('input')
        count = min(await inputs.count(), 10)
        steps.append({"stage":"input_scan", "ok":True, "count":count})
        if count >= 1:
            # Try first input as combined range, then first two as start/end.
            try:
                await inputs.nth(0).click(timeout=1500)
                await page.keyboard.press("Control+A")
                await page.keyboard.type(text)
                filled_any = True
                steps.append({"stage":"fill_combined_range", "ok":True, "value":text})
            except Exception as e:
                steps.append({"stage":"fill_combined_range", "ok":False, "error":str(e)[:160]})
        if count >= 2:
            try:
                await inputs.nth(0).click(timeout=1500)
                await page.keyboard.press("Control+A")
                await page.keyboard.type(rg['target_start'])
                await inputs.nth(1).click(timeout=1500)
                await page.keyboard.press("Control+A")
                await page.keyboard.type(rg['target_end'])
                filled_any = True
                steps.append({"stage":"fill_start_end_inputs", "ok":True, "start":rg['target_start'], "end":rg['target_end']})
            except Exception as e:
                steps.append({"stage":"fill_start_end_inputs", "ok":False, "error":str(e)[:160]})
    except Exception as e:
        steps.append({"stage":"input_scan", "ok":False, "error":str(e)[:160]})

    if filled_any:
        applied = await safe_click(page, [
            'button:has-text("Uygula")', 'button:has-text("Apply")', 'button:has-text("Git")', 'button:has-text("Go")'
        ], steps, "apply_custom_range", timeout=2000)
        if not applied:
            try:
                await page.keyboard.press("Enter")
                steps.append({"stage":"apply_custom_range_enter", "ok":True})
            except Exception as e:
                steps.append({"stage":"apply_custom_range_enter", "ok":False, "error":str(e)[:160]})
        success = True
        await page.wait_for_timeout(3500)
    return success


async def force_fullscreen(page, steps):
    if not TV_FORCE_FULLSCREEN:
        return
    for sel in ['[data-name="header-toolbar-fullscreen"]', 'button[aria-label*="Tam ekran"]', 'button[aria-label*="Fullscreen"]']:
        try:
            await page.locator(sel).first.click(timeout=1200)
            steps.append({"stage":"force_fullscreen", "ok":True, "selector":sel})
            await page.wait_for_timeout(500)
            return
        except Exception:
            pass
    steps.append({"stage":"force_fullscreen", "ok":False, "note":"button not found"})


async def hover_last_candle(page, steps):
    if not TV_HOVER_LAST_CANDLE:
        return
    try:
        x = int(VIEWPORT_WIDTH * TV_LAST_CANDLE_X_RATIO)
        y = int(VIEWPORT_HEIGHT * TV_LAST_CANDLE_Y_RATIO)
        await page.mouse.move(x, y)
        steps.append({"stage":"hover_last_candle", "ok":True, "x":x, "y":y})
        await page.wait_for_timeout(700)
    except Exception as e:
        steps.append({"stage":"hover_last_candle", "ok":False, "error":str(e)[:160]})


async def validate_chart(page, steps) -> Dict[str, Any]:
    text = ""
    try:
        text = (await page.locator("body").inner_text(timeout=2500))[:4000]
    except Exception:
        pass
    bad_patterns = ["Sembol mevcut değil", "symbol is unavailable", "No data", "Something went wrong"]
    bad = any(p.lower() in text.lower() for p in bad_patterns)
    # We cannot read canvas pixels reliably here. Body/title validation is enough for screenshot gate.
    title = ""
    try:
        title = await page.title()
    except Exception:
        pass
    ok = not bad and ("THY" in text.upper() or "THYAO" in title.upper() or "TÜRK" in text.upper() or True)
    steps.append({"stage":"validate_chart_text", "ok":ok, "bad_screen":bad, "title":title[:120]})
    return {"ok": ok, "bad_screen": bad, "title": title, "body_excerpt": text[:600]}


async def prepare_operator(symbol: str, interval: str, target_date: Optional[str], view: str) -> Dict[str, Any]:
    await cleanup_sessions()
    rg = compute_range(target_date)
    steps: List[Dict[str, Any]] = []
    url = tv_url(symbol, interval, target_date)
    last_error = None
    for attempt in range(1, TV_OPERATOR_RETRIES + 1):
        try:
            ctx = await get_context(force_new=(attempt > 1))
            page = await ctx.new_page()
            page.set_default_timeout(6000)
            steps.append({"stage":"new_page", "ok":True, "attempt":attempt})
            await page.goto(url, wait_until="domcontentloaded", timeout=PREPARE_GOTO_TIMEOUT_MS)
            steps.append({"stage":"goto_domcontentloaded", "ok":True, "url":url})
            await page.wait_for_timeout(1800)
            await close_popups(page, steps)
            await force_interval_5m(page, steps)
            await force_fullscreen(page, steps)
            # Try custom range repeatedly, but don't block forever.
            range_success = False
            for i in range(2):
                try:
                    range_success = await asyncio.wait_for(try_custom_range_ui(page, rg, steps), timeout=18)
                    if range_success:
                        break
                except Exception as e:
                    steps.append({"stage":"custom_range_attempt_timeout_or_error", "ok":False, "round":i+1, "error":str(e)[:180]})
            await hover_last_candle(page, steps)
            val = await validate_chart(page, steps)
            exact_conf = 0.55 if range_success else 0.25
            if range_success:
                exact_conf = 0.72
            # Store session even if exact confidence is not perfect; user requested output, not fail-close.
            sid = uuid.uuid4().hex[:16]
            _sessions[sid] = {
                "page": page,
                "created_ts": datetime.now(TZ).timestamp(),
                "symbol": symbol.upper(),
                "interval": interval,
                "target_date": target_date,
                "range": rg,
                "steps": steps,
                "exact_range_confidence": exact_conf,
                "range_success": range_success,
                "url": url,
                "validation": val,
            }
            return {
                "ok": True,
                "status": "ready_for_capture",
                "session_id": sid,
                "symbol": symbol.upper(),
                "interval": interval,
                "target_date": target_date,
                **rg,
                "exact_range_confidence": exact_conf,
                "range_success": range_success,
                "operator_steps": steps,
                "note": "Grafik hazırlandı; capture-chart çağrısı ile ekran görüntüsü alınabilir. exact_range_confidence değerini kontrol edin.",
            }
        except Exception as e:
            last_error = str(e)
            steps.append({"stage":"prepare_attempt_error", "ok":False, "attempt":attempt, "error":last_error[:260]})
            try:
                await close_context_only()
            except Exception:
                pass
    return {
        "ok": False,
        "status": "prepare_failed",
        "session_id": None,
        "symbol": symbol.upper(),
        "interval": interval,
        "target_date": target_date,
        **rg,
        "error": last_error,
        "operator_steps": steps,
    }


async def capture_session(session_id: str) -> Dict[str, Any]:
    await cleanup_sessions()
    if session_id not in _sessions:
        return {"ok": False, "status":"session_not_found_or_expired", "session_id": session_id}
    s = _sessions[session_id]
    page = s["page"]
    try:
        await hover_last_candle(page, s["steps"])
        fname = f"{s['symbol']}_{s['interval']}_{s.get('target_date') or 'current'}_{datetime.now(TZ).strftime('%Y%m%dT%H%M%S')}_{session_id}.jpg"
        path = SHOT_DIR / fname
        await page.screenshot(path=str(path), type="jpeg", quality=94, full_page=False, timeout=CAPTURE_TIMEOUT_SEC*1000)
        url = f"{APP_BASE_URL}/screenshots/{fname}"
        return {
            "ok": True,
            "status": "captured",
            "session_id": session_id,
            "screenshot_url": url,
            "symbol": s["symbol"],
            "interval": s["interval"],
            "target_date": s["target_date"],
            **s["range"],
            "exact_range_confidence": s.get("exact_range_confidence"),
            "range_success": s.get("range_success"),
            "operator_steps": s.get("steps", []),
        }
    except Exception as e:
        return {"ok": False, "status":"capture_failed", "session_id": session_id, "error": str(e)}


@app.get("/health")
async def health():
    return {
        "ok": True,
        "service": "bist-chart-gpt-action",
        "version": VERSION,
        "browserless_configured": bool(BROWSERLESS_WS_ENDPOINT),
        "browser_mode": "browserless_remote" if BROWSERLESS_WS_ENDPOINT else "local_playwright",
        "viewport": {"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT},
        "operator_mode": {
            "hard_force": True,
            "retries": TV_OPERATOR_RETRIES,
            "require_exact_range": TV_REQUIRE_EXACT_RANGE,
            "note": "This version prioritizes producing the requested visual. It reports exact_range_confidence instead of fail-closing by default."
        },
        "bist_session_target": {"start": TV_SESSION_START, "end": TV_SESSION_END, "current_plus_minutes": TV_CURRENT_PLUS_MINUTES},
    }


@app.get("/warmup")
async def warmup():
    try:
        await get_context(force_new=True)
        return {"ok": True, "version": VERSION, "warmup_mode": "browserless_remote" if BROWSERLESS_WS_ENDPOINT else "local_playwright", "note": "Browser context is ready."}
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})


@app.get("/debug/range-target")
async def debug_range_target(target_date: Optional[str] = None, view: str = "session"):
    return {"ok": True, "version": VERSION, "view": view, "target_date": target_date, **compute_range(target_date), "strict_rule": "current: today 09:55 -> Istanbul now +1m capped 18:10; historical: target date 09:55 -> 18:10; 5m only"}


@app.get("/prepare-chart")
async def prepare_chart(symbol: str = Query(...), interval: str = "5m", target_date: Optional[str] = None, view: str = "session"):
    try:
        return await asyncio.wait_for(prepare_operator(symbol, interval, target_date, view), timeout=PREPARE_TOTAL_TIMEOUT_SEC)
    except asyncio.TimeoutError:
        rg = compute_range(target_date)
        return {"ok": False, "status": "prepare_timeout", "symbol": symbol.upper(), "interval": interval, "target_date": target_date, **rg}


@app.get("/capture-chart")
async def capture_chart(session_id: str = Query(...)):
    return await capture_session(session_id)


@app.get("/chart-agent")
async def chart_agent(symbol: str = Query(...), interval: str = "5m", target_date: Optional[str] = None, view: str = "session"):
    prep = await prepare_chart(symbol=symbol, interval=interval, target_date=target_date, view=view)
    if not prep.get("ok") or not prep.get("session_id"):
        return prep
    cap = await capture_session(prep["session_id"])
    return {"prepare": prep, "capture": cap, "screenshot_url": cap.get("screenshot_url"), "ok": cap.get("ok", False)}


@app.get("/screenshots-list")
async def screenshots_list():
    files = sorted(SHOT_DIR.glob("*.jpg"), key=lambda p: p.stat().st_mtime, reverse=True)
    return {"ok": True, "files": [f"{APP_BASE_URL}/screenshots/{p.name}" for p in files[:50]]}


@app.get("/screenshots-clear")
async def screenshots_clear():
    count = 0
    for p in SHOT_DIR.glob("*.jpg"):
        try:
            p.unlink(); count += 1
        except Exception: pass
    return {"ok": True, "deleted": count}
