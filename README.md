# v7.4 Operator Mode Hard Force

Amaç: Analiz yapmadan sadece grafik görseli üretmek.

Bu sürüm fail-close yerine hard-operator mantığı kullanır:
- Browserless context reset/retry
- TradingView full chart açma
- 5dk interval zorlaması
- Özel tarih aralığına ulaşmak için çoklu UI stratejisi
- Son mum üstüne hover
- Screenshot üretme
- JSON'da `exact_range_confidence` ve `operator_steps` döndürme

Not: TradingView public UI özel aralık onayını programatik olarak her zaman garanti etmez. Bu sürüm başarısız demeyi azaltmak için çoklu rota dener; yine de `exact_range_confidence` alanını kontrol edin.
