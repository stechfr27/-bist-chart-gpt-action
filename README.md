# BIST Chart GPT Action API v1.9 Speed Optimized

Bu proje ChatGPT Custom GPT Actions için BIST grafik servisidir.

## Ana hedef

Güncel grafik istendiğinde doğruluğu bozmadan daha hızlı cevap vermek:

- TradingView mum grafik screenshot alınır.
- Midas direct ve BloombergHT direct hızlı teyit katmanı paralel çalışır.
- Yahoo/Stooq gibi yavaş OHLC kaynakları güncel hızlı modda beklenmez.
- Tarihli, dönemsel veya detaylı analizde `mode=balanced` ile Yahoo/Stooq OHLC katmanı çalışır.
- Screenshot, quote ve veri işleri paralel yürür; önceki sürümlerdeki sırayla bekleme azaltıldı.

## Deploy

1. Dosyaları GitHub repo köküne yükle.
2. Render üzerinde Web Service kullan.
3. Runtime Docker olmalı.
4. Deploy sonrası kontrol:

```text
https://SENIN-URL.onrender.com/health
```

Beklenen sürüm:

```json
{"version":"1.9.0-current-speed-optimized"}
```

## Warmup

Render free plan uyandığında ilk istek yavaş olabilir. Günlük kullanımdan önce:

```text
https://SENIN-URL.onrender.com/warmup
```

## Hızlı güncel grafik testi

```text
https://SENIN-URL.onrender.com/chart?symbol=THYAO&interval=5m&mode=current
```

Bu mod günlük kullanım için önerilir.

## Detaylı / tarihli analiz

```text
https://SENIN-URL.onrender.com/chart?symbol=THYAO&interval=5m&range_hint=5d&mode=balanced
```

```text
https://SENIN-URL.onrender.com/chart?symbol=THYAO&interval=1d&range_hint=3mo&mode=balanced
```

## Modlar

| Mod | Kullanım | Ne yapar |
|---|---|---|
| `current` | Güncel grafik | En hızlı güvenli mod: TradingView screenshot + Midas/Bloomberg direct teyit |
| `fast` | Hızlı ama Yahoo denensin | Yahoo OHLC dener, Stooq beklemez |
| `balanced` | Detaylı/tarihli/dönemsel | Yahoo + Stooq + daha geniş public kaynaklar |

## Custom GPT Action

`openapi_schema_for_gpt_action.json` içindeki server URL'ini kendi Render URL'inle değiştir.
Sonra Custom GPT > Configure > Actions > Create new action içine schema'yı yapıştır.

## Dürüst veri notu

Ücretsiz kaynaklarda BIST intraday veri gecikmeli, sınırlı veya dönemsel olarak eksik olabilir.
Derinlik, AKD/BOFA, karanlık oda ve emir defteri için aracı kurum ekranı gerekir.
