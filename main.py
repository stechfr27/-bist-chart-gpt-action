import base64
import io
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

import pandas as pd
import yfinance as yf
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from pydantic import BaseModel
from PIL import Image

app = FastAPI(
    title="BIST Chart GPT Action API",
    description="TradingView mum grafiği ekran görüntüsü + doğrulama amaçlı OHLC verisi döndürür.",
    version="1.0.0",
)

TV_INTERVALS = {"1m": "1", "3m": "3", "5m": "5", "10m": "10", "15m": "15", "30m": "30", "1h": "60", "1d": "D"}
YF_INTERVALS = {"1m", "5m", "15m", "30m", "60m", "1d"}

class ChartResponse(BaseModel):
    symbol: str
    interval: str
    range_hint: str
    source_chart: str
    source_data: str
    tradingview_url: str
    screenshot_base64_png: str
    ohlc_sample: list[dict]
    data_note: str
    captured_at_utc: str

@app.get("/health")
def health():
    return {"ok": True, "service": "bist-chart-gpt-action"}

def normalize_symbol(symbol: str) -> str:
    s = symbol.upper().replace(".IS", "").replace("BIST:", "").strip()
    if not s.isalnum():
        raise HTTPException(status_code=400, detail="Sembol sadece harf/rakam olmalı. Örn: THYAO, ASELS, TUPRS")
    return s

def make_tv_url(symbol: str, interval: str) -> str:
    tv_interval = TV_INTERVALS.get(interval, "5")
    return f"https://tr.tradingview.com/chart/?symbol=BIST:{symbol}&interval={tv_interval}"

def screenshot_tradingview(url: str, target_date: Optional[str] = None) -> str:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        page = browser.new_page(viewport={"width": 1440, "height": 950}, device_scale_factor=1)
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(7000)
            # Grafik alanına odaklanmak için mümkün olduğunca temiz ekran.
            for selector in ["button[aria-label='Close']", "button[data-name='close']"]:
                try:
                    page.locator(selector).first.click(timeout=1000)
                except Exception:
                    pass
            if target_date:
                # TradingView tarih navigasyonu URL ile garanti edilmediği için ekran görüntüsü güncel açılır;
                # tarihli veri doğrulama JSON tarafında yapılır.
                pass
            png = page.screenshot(full_page=False, type="png")
        except PlaywrightTimeoutError:
            raise HTTPException(status_code=504, detail="TradingView grafiği zamanında yüklenmedi.")
        finally:
            browser.close()
    return base64.b64encode(png).decode("utf-8")

def fetch_yahoo_ohlc(symbol: str, interval: str, period: str, target_date: Optional[str]) -> tuple[list[dict], str]:
    yf_symbol = f"{symbol}.IS"
    yf_interval = interval if interval in YF_INTERVALS else "5m"
    note = "Yahoo Finance doğrulama verisi; BIST verileri gecikmeli/eksik olabilir. Nihai karar için aracı kurum/Midas ekranı ile teyit önerilir."
    try:
        if target_date:
            d = datetime.strptime(target_date, "%Y-%m-%d")
            start = d - timedelta(days=3)
            end = d + timedelta(days=3)
            df = yf.download(yf_symbol, start=start.date().isoformat(), end=end.date().isoformat(), interval=yf_interval, progress=False, auto_adjust=False)
            if not df.empty:
                try:
                    df = df.loc[target_date]
                except Exception:
                    pass
        else:
            # Yahoo intraday kısıtları nedeniyle 1m kısa, 5m/15m daha geniş çalışır.
            yf_period = period if period in {"1d","5d","1mo","3mo","6mo","1y","2y","5y"} else "5d"
            df = yf.download(yf_symbol, period=yf_period, interval=yf_interval, progress=False, auto_adjust=False)
        if df is None or df.empty:
            return [], note + " Veri bulunamadı."
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [c[0] for c in df.columns]
        df = df.reset_index().tail(120)
        rows = []
        for _, r in df.iterrows():
            dt_val = r.get("Datetime", r.get("Date", ""))
            rows.append({
                "time": str(dt_val),
                "open": None if pd.isna(r.get("Open")) else round(float(r.get("Open")), 4),
                "high": None if pd.isna(r.get("High")) else round(float(r.get("High")), 4),
                "low": None if pd.isna(r.get("Low")) else round(float(r.get("Low")), 4),
                "close": None if pd.isna(r.get("Close")) else round(float(r.get("Close")), 4),
                "volume": None if pd.isna(r.get("Volume")) else int(float(r.get("Volume"))),
            })
        return rows, note
    except Exception as e:
        return [], note + f" Veri çekim hatası: {type(e).__name__}"

@app.get("/chart", response_model=ChartResponse)
def get_chart(
    symbol: str = Query(..., description="BIST sembolü. Örn: THYAO, ASELS, TUPRS"),
    interval: Literal["1m","3m","5m","10m","15m","30m","1h","1d"] = Query("5m"),
    range_hint: str = Query("5d", description="1d, 5d, 1mo, 3mo, 6mo, 1y gibi niyet bilgisi"),
    target_date: Optional[str] = Query(None, description="YYYY-MM-DD. Örn: 2026-06-04"),
):
    s = normalize_symbol(symbol)
    url = make_tv_url(s, interval)
    shot = screenshot_tradingview(url, target_date=target_date)
    ohlc, note = fetch_yahoo_ohlc(s, interval, range_hint, target_date)
    return ChartResponse(
        symbol=s,
        interval=interval,
        range_hint=range_hint,
        source_chart="TradingView visual chart screenshot",
        source_data="Yahoo Finance OHLC fallback/verification",
        tradingview_url=url,
        screenshot_base64_png=shot,
        ohlc_sample=ohlc,
        data_note=note,
        captured_at_utc=datetime.now(timezone.utc).isoformat(),
    )
