# BIST Chart GPT Action API

Bu paket, ChatGPT Custom GPT Actions ile çalışacak şekilde hazırlanmıştır.

Amaç: Kullanıcı ChatGPT'ye “THYAO güncel 5dk grafiğini incele” veya “ASELS 2026-06-04 grafiğine bak” dediğinde API:

1. TradingView üzerinde ilgili BIST grafiğini açar.
2. Mum grafik ekran görüntüsü alır.
3. Görseli `screenshot_url` olarak döndürür.
4. Yahoo Finance üzerinden `.IS` formatıyla doğrulama/eksik veri tamamlama amaçlı OHLC ve hacim örneği ekler.
5. ChatGPT'ye JSON olarak döndürür.

## v1.1 güncellemesi

- Yahoo Finance sembol formatı kesin olarak `THYAO.IS`, `ASELS.IS`, `TUPRS.IS` mantığına alındı.
- Yahoo veri boş gelirse alternatif `download` ve `Ticker.history` fallback denemeleri eklendi.
- 3m ve 10m gibi Yahoo tarafından desteklenmeyen aralıklar otomatik en yakın güvenli intervale çevrilir.
- `screenshot_base64_png` varsayılan olarak kapatıldı; cevap şişmesin diye `screenshot_url` döner.
- `include_base64=true` verilirse base64 görüntü yine alınabilir.
- `data_status`, `ohlc_count`, `yahoo_symbol`, `yahoo_interval_used` alanları eklendi.

## Dosyalar

- `main.py`: FastAPI servis kodu
- `Dockerfile`: Playwright/Chromium destekli deploy imajı
- `requirements.txt`: Python paketleri
- `render.yaml`: Render deploy ayarı
- `openapi_schema_for_gpt_action.json`: Custom GPT Actions şeması
- `custom_gpt_instructions.txt`: GPT'ye yapıştırılacak talimat

## Deploy

1. GitHub'daki eski dosyaların üstüne bu yeni dosyaları yükle.
2. Render otomatik deploy açıksa kendisi yeniden deploy eder.
3. Otomatik deploy kapalıysa Render panelinde `Manual Deploy > Deploy latest commit` yap.
4. Deploy bitince health testini aç:

`https://SENIN-URL.onrender.com/health`

Beklenen:

`{"ok": true, "service": "bist-chart-gpt-action", "version": "1.1.0-yahoo-fallback-fix"}`

## Test linkleri

Güncel 5dk THYAO:

`https://SENIN-URL.onrender.com/chart?symbol=THYAO&interval=5m&range_hint=5d`

Base64 de istiyorsan:

`https://SENIN-URL.onrender.com/chart?symbol=THYAO&interval=5m&range_hint=5d&include_base64=true`

Belirli tarih:

`https://SENIN-URL.onrender.com/chart?symbol=THYAO&interval=5m&target_date=2026-06-04`

3 aylık günlük:

`https://SENIN-URL.onrender.com/chart?symbol=ASELS&interval=1d&range_hint=3mo`

## Önemli not

TradingView ekran görüntüsü görsel kaynak; Yahoo Finance verisi doğrulama ve eksik veri tamamlama amaçlıdır. BIST intraday verileri ücretsiz kaynaklarda gecikmeli veya kısıtlı olabilir. Kesin işlem öncesi aracı kurum ekranı ile teyit gerekir.
