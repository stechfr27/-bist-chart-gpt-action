# v5.9 local preflight
- Python compile: expected pass
- FastAPI import/health: expected pass
- New env aliases supported:
  - CHART_TOTAL_TIMEOUT_SEC -> TV_CURRENT_HARD_TIMEOUT_SECONDS/TOTAL_CHART_HARD_TIMEOUT_SECONDS
  - TV_RANGE_MAX_SECONDS -> TV_CUSTOM_RANGE_MAX_SECONDS
  - TV_FULL_CHART_BUDGET_SECONDS controls full TradingView wrapper budget
- Goal: prevent wrapper timeout at fixed 42s before range debug can surface.
