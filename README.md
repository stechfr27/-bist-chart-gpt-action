# BIST Chart GPT Action v5.5 - Graph Only

This version focuses only on returning a verified TradingView chart screenshot.
It intentionally skips Yahoo/Stooq/Midas/Bloomberg/Borsa Istanbul data calls.

Required env:
- BROWSERLESS_WS_ENDPOINT
- PORT=10000
- PYTHONUNBUFFERED=1

Main endpoint:
- /chart?symbol=THYAO&interval=5m&mode=current&view=session

Rule: if screenshot_url is null, the GPT must not do chart analysis.
