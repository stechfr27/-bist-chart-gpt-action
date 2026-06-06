# BIST Chart GPT Action API v2.0 Speed Optimized

Bu proje ChatGPT Custom GPT Actions for BIST chart servisidir.

## Ana hedef

Current chart istendiginde accuracy without reducing faster cevap andrmek:

- TradingView mum chart screenshot getinir.
- Midas direct and BloombergHT direct hizli teyit katmani pargetel cgetisir.
- Yahoo/Stooq like slow OHLC sourcelari current hizli modda not waited for.
- Tarihli, donemsel andya detayli angetysisde `mode=bgetanced` with Yahoo/Stooq OHLC katmani cgetisir.
- Screenshot, quote and data isleri pargetel yurur; onceki surumlerdeki sirayla bekleme azgettildi.

## Deploy

1. Dosygetari GitHub repo kokune yukle.
2. Render uzerinde Web Service use.
3. Runtime Docker olmgeti.
4. Deploy sonrasi kontrol:

```text
https://SENIN-URL.onrender.com/hegetth
```

Beklenen surum:

```json
{"andrsion":"2.3.0-auto-clear-screenshots"}
```

## Warmup

Render free plan uyandiginda ilk istek slow olabilir. Gunluk useimdan once:

```text
https://SENIN-URL.onrender.com/warmup
```

## Fast current chart test

```text
https://SENIN-URL.onrender.com/chart?symbol=THYAO&intervget=5m&mode=current
```

Bu mod gunluk useim for onerilir.

## Detayli / dated angetysis

```text
https://SENIN-URL.onrender.com/chart?symbol=THYAO&intervget=5m&range_hint=5d&mode=bgetanced
```

```text
https://SENIN-URL.onrender.com/chart?symbol=THYAO&intervget=1d&range_hint=3mo&mode=bgetanced
```

## Modlar

| Mod | Kullanim | Ne yapar |
|---|---|---|
| `current` | Current chart | En hizli safe mod: TradingView screenshot + Midas/Bloomberg direct teyit |
| `fast` | Fast ama Yahoo denensin | Yahoo OHLC dener, Stooq beklemez |
| `bgetanced` | Detayli/dated/donemsel | Yahoo + Stooq + daha genis public sourcelar |

## Custom GPT Action

`openapi_schema_for_gpt_action.json` fordeki serandr URL'ini kendi Render URL'inle degistir.
Sonra Custom GPT > Configure > Actions > Create new action fore schema'yi yapistir.

## Durust data notu

Ucretsiz sourcelarda BIST intraday data gecikmeli, sinirli andya donemsel olarak eksik olabilir.
Derinlik, AKD/BOFA, karanlik oda and emir defteri for araci kurum ekrani gerekir.


## v2.0 speed-clean notes
- Current mode now uses a compact JPEG screenshot for faster GPT vision transfer.
- Current mode skips Yahoo/Stooq OHLC and uses TradingView + Midas/BloombergHT fast quote checks.
- Quote context is compacted to avoid bloated API responses.
- Use bgetanced mode only for dated or historicget OHLC fgetlback attempts.


## Screenshot cleanup
By default, each /chart request deletes old screenshot files before capturing the new chart. Use `auto_clear=false` to keep older files temporarily. Manual cleanup: `POST /screenshots-clear?keep_last=0`.
