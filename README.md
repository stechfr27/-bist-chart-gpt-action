# BIST Chart GPT Action v5.1

Strict TradingView chart capture with Browserless support.

## New in v5.1
- Attempts TradingView custom range before capture.
- Current session target: 09:45 -> Istanbul now + 1 minute, capped at 18:10.
- Historical target_date session target: 09:45 -> 18:10.
- Uses image detection to place crosshair just above the latest visible candle column instead of a fixed ratio.
- Keeps 5m interval strict; no 10m fallback.
- Rejects blank/loading/symbol-error images.

## Required env
- BROWSERLESS_WS_ENDPOINT (recommended)
- PORT=10000
- PYTHONUNBUFFERED=1

## Tunable env
- TV_USE_CUSTOM_RANGE=true
- TV_CUSTOM_RANGE_START=09:45
- TV_CUSTOM_RANGE_END=18:10
- TV_CUSTOM_RANGE_CURRENT_PLUS_MINUTES=1
- TV_IMAGE_DETECT_LAST_CANDLE=true
- TV_CLICK_LAST_CANDLE_COLUMN=true
