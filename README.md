# BIST Chart GPT Action v7.3 - Exact Range Forced Visual

Bu sürüm analiz yapmaz; sadece istenen BIST grafiğini görsel olarak üretmeye çalışır.

Yeni kritik kural: Yanlış/multi-day TradingView ekranı dönmek yasaktır. `TV_REQUIRE_EXACT_RANGE=true` varsayılandır. TradingView custom range menüsü üzerinden 09:55-18:10 aralığı doldurulup uygulanmadıysa `prepare_failed_exact_range_not_confirmed` döner ve screenshot engellenir.

## Health
`/health` içinde version şu olmalı:
`7.3.0-exact-range-forced-visual`

## Akış
1. `/prepare-chart?symbol=THYAO&interval=5m&target_date=2026-06-02&view=session`
2. `session_id` gelirse `/capture-chart?session_id=...`

## Önerilen env
- BROWSERLESS_WS_ENDPOINT=...
- CHART_TOTAL_TIMEOUT_SEC=58
- TV_RANGE_MAX_SECONDS=16
- TV_USE_CUSTOM_RANGE=true
- TV_REQUIRE_EXACT_RANGE=true
- TV_CUSTOM_RANGE_STRICT_FILL=true
- TV_HOVER_LAST_CANDLE=true
- TV_CLICK_LAST_CANDLE_COLUMN=false

## Önemli
Bu sürüm “zorla doğru grafik” prensibiyle fail-closed çalışır: yanlış tarih/seans görüntüsü döndürmez.
