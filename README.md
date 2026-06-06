# BIST Chart GPT Action API v3.5

Strict TradingView chart screenshot service for ChatGPT Actions. This version prioritizes a clear **full-day/session view**: when the user asks for "son gün", the chart tries to show the latest BIST session open-to-close from open to close, not an over-zoomed partial slice.

## New in v3.5

- Default `view=session` for current chart requests.
- Full TradingView chart is prioritized for session view so the right-side symbol info panel remains visible.
- Adds `range=1D` and soft-clicks the TradingView `1G/1D` range control when available.
- Wider viewport: default `1920x1080`.
- Local/widget paths are skipped in session mode because they can be cramped or show symbol errors for BIST.
- Browserless remote browser support remains active via `BROWSERLESS_WS_ENDPOINT`.
- Strict rule remains: loading/blank/symbol-error screenshots are rejected.

## Required env vars

```text
PORT=10000
PYTHONUNBUFFERED=1
BROWSERLESS_WS_ENDPOINT=wss://chrome.browserless.io?token=YOUR_TOKEN
```

Optional viewport override:

```text
TV_VIEWPORT_WIDTH=1600
TV_VIEWPORT_HEIGHT=1000
```

## Test order

```text
/health
/warmup
/chart?symbol=THYAO&interval=5m&mode=current&view=session
```

For a dated request:

```text
/chart?symbol=THYAO&interval=5m&target_date=2026-06-03&mode=balanced&view=session
```

Note: public TradingView exact historical date navigation is best-effort. The action still requests a session view and uses OHLC data for date verification when available.


## v3.7 session tight fit
- Default viewport: 2048x1152.
- Default SESSION_ZOOM_STEPS=8 and stronger wheel zoom.
- Goal: reduce previous-session spillover and make the latest BIST full session clearer while keeping the right info panel visible.
- If too zoomed: set SESSION_ZOOM_STEPS=6. If still too wide: set SESSION_ZOOM_STEPS=10.


## v3.8 chart-only note
Screenshots crop out the TradingView right watchlist/info sidebar by default. Price, change, volume and context should be read from quote_snapshots / Midas / BloombergHT fields, while the image is used primarily for candle and volume-bar analysis. Use CHART_ONLY_SCREENSHOT=false only if you explicitly want the full sidebar in the image.
