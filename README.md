# BIST Chart GPT Action v5.4

Range-core debug/budgeted build.

Core rules:
- Current request target: Istanbul today 09:55 -> current Istanbul time + 1 minute, capped at 18:10.
- Historical target_date request: target date 09:55 -> 18:10.
- 5m stays strict; no 10m/15m fallback.
- TradingView actual chart image only; no Midas/Bloomberg visual fallback.
- Last-candle hover remains enabled above the detected final candle column.
- Custom range is a core target and each stage is reported in `data_note`.

Important env vars:
- `BROWSERLESS_WS_ENDPOINT`: Browserless websocket endpoint.
- `TV_CUSTOM_RANGE_MAX_SECONDS=11` default.
- `TV_USE_CUSTOM_RANGE=true` default.
- `TV_HOVER_LAST_CANDLE=true` default.
