# v5.8 Local Self-Test Report

Tested locally without using Browserless token.

Passed checks:
- Python compile: `python -m py_compile main.py`
- FastAPI import and TestClient boot
- `/health` endpoint returns version `5.8.0-range-first-light-debug`
- `/debug/range-target` current calculation returns BIST session target 09:55 -> min(now+1m, 18:10)
- `/debug/range-target?target_date=2026-06-02` returns `02.06.2026 09:55` -> `02.06.2026 18:10`
- `/chart` response schema works with mocked screenshot engine
- `range_attempt.stages` is parsed into JSON when screenshot engine returns range stage notes
- invalid symbols and invalid intervals return HTTP 400

Not tested locally:
- Live Browserless token connection
- Live TradingView UI/custom range menu interaction
- Real screenshot generation from TradingView

Reason: Browserless token is stored only in the user's Render environment and should not be shared.
