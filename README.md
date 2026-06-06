# BIST Chart GPT Action v4.0

Strict TradingView chart capture with BIST session target + TradingView fullscreen/last-candle hover 09:55-18:10.

Key env vars:
- BROWSERLESS_WS_ENDPOINT: Browserless WebSocket endpoint
- PORT=10000
- BIST_SESSION_START=09:55
- BIST_SESSION_END=18:10
- SESSION_LEFT_CROP_RATIO=0.36 (tune 0.28-0.42)

Endpoints:
- /health
- /warmup
- /chart?symbol=THYAO&interval=5m&mode=current&view=session


## v4.1 additions
- Attempts TradingView fullscreen/expanded chart before capture.
- Moves/clicks the crosshair just above the latest candle column so the top OHLC/volume legend reflects that candle.
- Configurable env: TV_FORCE_FULLSCREEN, TV_HOVER_LAST_CANDLE, TV_CLICK_LAST_CANDLE_COLUMN, TV_LAST_CANDLE_X_RATIO, TV_LAST_CANDLE_Y_RATIO.
