# BIST Chart GPT Action v5.0 - Snapshot Download First

Bu surum TradingView grafik goruntusunu almadan once sitenin kendi snapshot/download-image akisini dener. Basarisiz olursa strict viewport screenshot fallback kullanir.

## Env
- `BROWSERLESS_WS_ENDPOINT`: Browserless WebSocket endpoint. Secret olarak ekle.
- `PORT=10000`
- `PYTHONUNBUFFERED=1`
- `TV_SNAPSHOT_DOWNLOAD_FIRST=true` varsayilan.
- `TV_SNAPSHOT_TIMEOUT_MS=9000`

## Test
- `/health`
- `/warmup`
- `/chart?symbol=THYAO&interval=5m&mode=current&view=session`

JSON'da `capture_method_used` alanini kontrol et:
- `tradingview_download_image`: sitenin kendi export/snapshot yolu calisti.
- `browser_viewport_screenshot`: export olmadi, strict screenshot fallback calisti.
- `none`: dogrulanmis grafik yok, analiz yapma.
