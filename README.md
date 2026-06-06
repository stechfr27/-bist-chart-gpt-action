# BIST Chart GPT Action API v3.2

Strict TradingView chart screenshot service for ChatGPT Actions.

## New in v3.2

- Optional Browserless remote browser support.
- Set `BROWSERLESS_WS_ENDPOINT` as a secret environment variable.
- If configured, the API uses Browserless Chrome via Playwright CDP.
- If not configured, it falls back to local Chromium.
- `/warmup` only starts the browser/context; it does not load TradingView.
- `/chart` remains strict: no loading/blank screenshot and no non-chart visual fallback.

## Required env vars

```text
PORT=10000
PYTHONUNBUFFERED=1
BROWSERLESS_WS_ENDPOINT=wss://chrome.browserless.io?token=YOUR_TOKEN
```

Do not put the Browserless token in GitHub files. Add it only in Render/Northflank environment variables or secrets.

## Test order

```text
/health
/warmup
/chart?symbol=THYAO&interval=5m&mode=current
```

A successful Browserless setup should show:

```json
{
  "browserless_configured": true,
  "browser_mode": "browserless_remote"
}
```

For real chart success, `/chart` should return `screenshot_url` and a TradingView chart status.
