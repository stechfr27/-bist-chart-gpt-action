import base64
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal, Optional

import pandas as pd
import yfinance as yf
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.staticfiles import StaticFiles
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError, sync_playwright
from pydantic import BaseModel, Field

APP_VERSION = "1.1.0-yahoo-fallback-fix"
SCREENSHOT_DIR = Path(os.getenv("SCREENSHOT_DIR", "/tmp/bist_chart_screenshots"))
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(
    title="BIST Chart GPT Action API",
    description="TradingView mum grafik ekran görüntüsü + Yahoo Finance OHLC doğrulama/eksik veri tamamlama servisi.",
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


def yf_download_with_fallbacks(yf_symbol: str, yf_interval: str, period: str, target_date: Optional[str]) -> tuple[list[dict], str, str]:
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

        # Intraday için hedef gün çevresini dene; tarih eskiyse Yahoo intraday dönmeyebilir.
        attempts.append({"mode": "download_date_intraday", "start": d - timedelta(days=4), "end": d + timedelta(days=4), "interval": yf_interval})
        # Günlük veri fallback: eski tarihlerde daha güvenilir.
        attempts.append({"mode": "download_date_daily", "start": d - timedelta(days=7), "end": d + timedelta(days=7), "interval": "1d"})
    else:
        safe_period = period if period in YF_ALLOWED_PERIODS else "5d"
        attempts.append({"mode": "download_period", "period": safe_period, "interval": yf_interval})
        if yf_interval != "1d":
            attempts.append({"mode": "download_period_daily", "period": "3mo" if safe_period in {"1mo", "3mo", "6mo", "1y"} else "1mo", "interval": "1d"})

    last_error = None
    used_interval = yf_interval

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
                used_interval = attempt["interval"]
                if attempt["interval"] != yf_interval:
                    return rows, "partial_fallback", base_note + f" İstenen Yahoo intervali bulunamadı; fallback olarak {attempt['interval']} döndü."
                return rows, "ok", base_note
        except Exception as e:
            last_error = f"{type(e).__name__}: {e}"

    # yfinance Ticker.history fallback.
    try:
        ticker = yf.Ticker(yf_symbol)
        if target_date:
            d = datetime.strptime(target_date, "%Y-%m-%d").date()
            df = ticker.history(start=(d - timedelta(days=7)).isoformat(), end=(d + timedelta(days=7)).isoformat(), interval="1d", auto_adjust=False)
            rows = clean_ohlc_df(df, target_date=target_date)
            used_interval = "1d"
        else:
            df = ticker.history(period="1mo", interval=yf_interval, auto_adjust=False)
            rows = clean_ohlc_df(df, target_date=None)
            used_interval = yf_interval
        if rows:
            return rows, "ok_ticker_history", base_note + " Veri yfinance Ticker.history fallback yöntemiyle alındı."
    except Exception as e:
        last_error = f"{type(e).__name__}: {e}"

    msg = base_note + " Yahoo Finance veri bulunamadı. Sembol .IS formatıyla denendi."
    if last_error:
        msg += f" Son hata: {last_error}"
    return [], "no_yahoo_data", msg


def fetch_yahoo_ohlc(symbol: str, interval: str, period: str, target_date: Optional[str]) -> tuple[list[dict], str, str, str, str]:
    yf_symbol = make_yahoo_symbol(symbol)
    yf_interval = YF_INTERVALS.get(interval, "5m")
    rows, status, note = yf_download_with_fallbacks(yf_symbol, yf_interval, period, target_date)
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
        source_data="Yahoo Finance OHLC fallback/verification/completion",
        tradingview_url=url,
        screenshot_url=absolute_url(request, image_route),
        screenshot_base64_png=image_b64,
        ohlc_sample=ohlc,
        ohlc_count=len(ohlc),
        data_status=status,
        data_note=note,
        captured_at_utc=datetime.now(timezone.utc).isoformat(),
    )
