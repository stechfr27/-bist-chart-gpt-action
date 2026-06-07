# BIST Chart GPT Action v7.0 — Prepare → Capture Agent

Bu sürüm tek endpoint yerine iki aşamalı çalışır:

1. `/prepare-chart` grafiği TradingView üzerinde hazırlar ve `session_id` döndürür.
2. `/capture-chart` aynı `session_id` ile hazır ekrandan screenshot alır.

Amaç, Custom GPT'nin “hazırla” ve “çek” komutlarını ayrı ayrı vermesidir.

## Render Environment

Zorunlu:

```text
BROWSERLESS_WS_ENDPOINT=wss://chrome.browserless.io?token=...
PORT=10000
PYTHONUNBUFFERED=1
```

Önerilen:

```text
BROWSERLESS_TIMEOUT_MS=60000
CHART_TOTAL_TIMEOUT_SEC=58
TV_RANGE_MAX_SECONDS=16
TV_USE_CUSTOM_RANGE=true
TV_HOVER_LAST_CANDLE=true
TV_CLICK_LAST_CANDLE_COLUMN=false
PREPARE_SESSION_TTL_SECONDS=70
TV_PREPARE_GOTO_TIMEOUT_MS=12000
```

## Test Sırası

```text
/health
/debug/range-target?target_date=2026-06-02
/prepare-chart?symbol=THYAO&interval=5m&target_date=2026-06-02&view=session
/capture-chart?session_id=GELEN_SESSION_ID
```

## Custom GPT Action

`gpt_schema_v7.json` dosyasını Custom GPT → Actions → Create new action kısmına koy.

