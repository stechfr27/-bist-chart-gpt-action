# BIST Chart GPT Action API v3.0

Strict graph-first version.

## Core rule
The `/chart` endpoint returns only a verified TradingView chart screenshot as `screenshot_url`.
It does not return Midas/Bloomberg/other public pages as a chart image.
It also rejects blank/loading TradingView screenshots.

## Capture order
1. Local minimal TradingView Advanced Chart Widget HTML
2. Official TradingView widgetembed
3. Full TradingView chart page

## Modes
- `mode=current`: fastest current-chart mode.
- `mode=safe_current`: longer strict TradingView capture for important checks.
- `mode=balanced`: slower historical/OHLC helper mode.

If all strict TradingView capture paths fail on Render, `screenshot_url` remains null and `chart_status` explains why. This is deliberate: the service will not fake a chart with a non-chart fallback.

## Useful endpoints
- `/health`
- `/warmup`
- `/chart?symbol=THYAO&interval=5m&mode=current`
- `/screenshots-list`
- `/screenshots-clear`
