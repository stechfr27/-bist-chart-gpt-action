# BIST Grafik Görseli Getirici v7.2

Bu sürümün tek görevi grafik görseli üretmektir. Teknik analiz yapmaz.

## Ana akış
1. `/prepare-chart` grafiği hazırlar ve `session_id` döndürür.
2. `/capture-chart` bu session ile screenshot alır ve `screenshot_url` döndürür.
3. Custom GPT kullanıcıya sadece görsel linkini verir.

## Custom GPT
- `gpt_schema_v7.json` dosyasını Actions schema alanına yapıştır.
- `custom_gpt_prompt_v7.txt` dosyasını Instructions alanına yapıştır.
- Server URL kısmını kendi Render URL'inle aynı bırak/değiştir.

## Önemli
`screenshot_url` yoksa grafik alınamamış demektir. Bu durumda analiz veya yorum yapılmaz.
