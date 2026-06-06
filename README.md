# BIST Chart GPT Action v2.5

Fast and safe current-chart mode for BIST symbols.

## Modes

- `mode=current`: default. 45-second visual-safe hard timeout. Uses TradingView screenshot + Midas/BloombergHT quote checks. Skips Yahoo/Stooq for speed.
- `mode=safe_current`: 60-second visual-safe hard timeout for important current checks.
- `mode=balanced`: slower historical/OHLC mode, up to about 115 seconds.

The API rejects loading/blank TradingView screenshots. If a verified chart cannot be captured in time, `screenshot_url` is `null`; quote layers still return.

## Test

`/health`
`/warmup`
`/chart?symbol=THYAO&interval=5m&mode=current`
`/chart?symbol=THYAO&interval=5m&mode=safe_current`
