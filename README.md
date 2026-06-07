# BIST Chart GPT Action v6.1

Browserless-key screen capture sürümü. PagePixels iptal edildi. Bu sürüm mevcut `BROWSERLESS_WS_ENDPOINT` anahtarını kullanır ve TradingView grafik görüntüsü almaya odaklanır.

## Required env
- `BROWSERLESS_WS_ENDPOINT`
- `PORT=10000`
- `PYTHONUNBUFFERED=1`

## Recommended env
- `CHART_TOTAL_TIMEOUT_SEC=58`
- `TV_FULL_CHART_BUDGET_SECONDS=55`
- `TV_RANGE_MAX_SECONDS=16`
- `TV_USE_CUSTOM_RANGE=true`
- `TV_HOVER_LAST_CANDLE=true`
- `TV_CLICK_LAST_CANDLE_COLUMN=false`

## Endpoints
- `/health`
- `/debug/range-target`
- `/chart`
