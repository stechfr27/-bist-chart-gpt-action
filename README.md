# BIST Chart GPT Action v1.3

Bu servis, Custom GPT Action üzerinden BIST hisseleri için grafik ekran görüntüsü ve çok kaynaklı fiyat/veri teyidi döndürür.

## Kaynak mantığı

- TradingView: ana mum grafik screenshot kaynağı.
- Yahoo Finance: OHLC doğrulama / eksik veri tamamlama.
- Stooq: Yahoo tıkanırsa günlük OHLC fallback.
- Midas Canlı Borsa: ücretsiz web fiyat teyidi, sayfada 15 dakika gecikme notu bulunur.
- BloombergHT Borsa: görünür borsa tablolarından özet fiyat/hacim teyidi.
- Investing.com TR: görünür piyasa listelerinden özet fiyat teyidi.
- Borsa İstanbul: resmi veri/duyuru/günlük bülten referansı; ücretsiz canlı intraday mum kaynağı gibi kullanılmaz.

## Deploy

1. Dosyaları GitHub reposuna yükle.
2. Render'da Web Service oluştur.
3. Runtime olarak Docker kullan.
4. Deploy sonrası `/health` endpoint'ini test et.

Beklenen health cevabı:

```json
{"ok":true,"service":"bist-chart-gpt-action","version":"1.3.0-public-source-fallbacks"}
```

## Test

```text
https://SENIN-URL.onrender.com/chart?symbol=THYAO&interval=5m&range_hint=5d
```

Cevapta şunları görmelisin:

- `screenshot_url`
- `ohlc_sample`
- `quote_snapshots`
- `official_reference`
- `data_status`
- `data_note`

## Notlar

Ücretsiz kaynaklar intraday mum verisini her zaman eksiksiz sağlamaz. Bu yüzden sistem görsel grafik + sayısal doğrulama + ek fiyat teyidi mantığıyla çalışır. Emir defteri, AKD/BOFA, karanlık oda ve derinlik verisi için aracı kurum ekranı gerekir.
