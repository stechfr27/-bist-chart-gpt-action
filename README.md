# BIST Chart GPT Action API

Bu paket, ChatGPT Custom GPT Actions ile çalışacak şekilde hazırlanmıştır.

Amaç: Kullanıcı ChatGPT'ye “THYAO güncel 5dk grafiğini incele” veya “ASELS 2026-06-04 grafiğine bak” dediğinde API:

1. TradingView üzerinde ilgili BIST grafiğini açar.
2. Mum grafik ekran görüntüsü alır.
3. Yahoo Finance üzerinden doğrulama amaçlı OHLC örneği ekler.
4. ChatGPT'ye JSON olarak döndürür.

## Dosyalar

- `main.py`: FastAPI servis kodu
- `Dockerfile`: Playwright/Chromium destekli deploy imajı
- `requirements.txt`: Python paketleri
- `render.yaml`: Render deploy ayarı
- `openapi_schema_for_gpt_action.json`: Custom GPT Actions şeması
- `custom_gpt_instructions.txt`: GPT'ye yapıştırılacak talimat

## Deploy

1. GitHub'da yeni repo aç.
2. Bu dosyaları yükle.
3. Render veya Docker destekli başka bir bulut servisine deploy et.
4. Deploy URL'ni al.
5. `openapi_schema_for_gpt_action.json` içindeki `https://YOUR-DEPLOYED-URL.onrender.com` kısmını kendi URL'inle değiştir.
6. Custom GPT oluştururken Actions bölümüne bu şemayı yapıştır.
7. Instructions kısmına `custom_gpt_instructions.txt` içeriğini ekle.

## Test

Tarayıcıdan:

`https://SENIN-URL/chart?symbol=THYAO&interval=5m&range_hint=5d`

## Önemli not

TradingView ekran görüntüsü görsel kaynak; Yahoo Finance verisi doğrulama amaçlıdır. BIST intraday verileri ücretsiz kaynaklarda gecikmeli veya kısıtlı olabilir. Kesin işlem öncesi aracı kurum ekranı ile teyit gerekir.
