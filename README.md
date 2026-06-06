# BIST Chart GPT Action API v1.5 Final

Bu proje ChatGPT Custom GPT Actions ile kullanılmak üzere hazırlanmış BIST grafik servisidir.

## Ne yapar?

- TradingView üzerinde BIST sembolünü açar ve mum grafik screenshot alır.
- Yahoo Finance üzerinden `.IS` sembolüyle OHLC verisi dener.
- Yahoo rate limit/boş veri verirse Stooq günlük OHLC fallback dener.
- Midas, BloombergHT ve Investing gibi ücretsiz public sayfalardan ek quote/context teyidi alır.
- Borsa İstanbul'u resmi referans katmanı olarak döndürür.
- TradingView geç yüklenirse API tamamen patlamaz; screenshot başarısız olsa bile veri katmanlarını döndürür.
- Kalıcı Playwright browser/context kullanır. Bu, her istekte Chromium'u sıfırdan açmaktan daha stabildir.

## Deploy

1. Dosyaları GitHub repo köküne yükle.
2. Render üzerinde Web Service oluştur.
3. Runtime olarak Docker kullan.
4. Deploy sonrası kontrol:

```text
https://SENIN-URL.onrender.com/health
```

Beklenen sürüm:

```json
{"version":"1.6.0-source-url-encoding-fix"}
```

## Warmup

Render free plan uyandığında ilk TradingView isteği yavaş olabilir. Önce bunu çağırabilirsin:

```text
https://SENIN-URL.onrender.com/warmup
```

## Grafik testi

```text
https://SENIN-URL.onrender.com/chart?symbol=THYAO&interval=5m&range_hint=5d
```

## Custom GPT Action

`openapi_schema_for_gpt_action.json` içindeki server URL'ini kendi Render URL'inle değiştir.
Sonra Custom GPT > Configure > Actions > Create new action içine schema'yı yapıştır.

## Opsiyonel TradingView Cookie

TradingView public sayfası sık engel çıkarırsa Render environment variable olarak şunu ekleyebilirsin:

```text
TRADINGVIEW_COOKIE=...
```

Bunu paylaşma. Hesap/session bilgisi içerebilir.

## Dürüst veri notu

Ücretsiz kaynaklarda BIST intraday veri gecikmeli, sınırlı veya dönemsel olarak eksik olabilir.
Derinlik, AKD/BOFA, karanlık oda ve emir defteri için aracı kurum ekranı gerekir.
