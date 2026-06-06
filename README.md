# BIST Chart GPT Action v4.0

Strict TradingView chart capture with BIST session target 09:55-18:10.

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
