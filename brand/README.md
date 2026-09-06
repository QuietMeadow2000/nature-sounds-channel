# Quiet Meadow — marka dosyaları

Aynı işaretin iki kilidi: halkasız (serbest) ve halkalı (kapsanmış).

| Dosya | Boyut | Nerede |
|---|---|---|
| `logo.png` | 512×512, şeffaf beyaz | Thumbnail sağ alt köşesi. Drive'da `nature-sounds-assets/logo.png` olarak durmalı — pipeline oradan indiriyor. |
| `profile.png` | 800×800 | YouTube kanal profil fotoğrafı. Halkalı versiyon; avatar dairesi içinde işarete sınır veriyor. |
| `banner.png` | 2560×1440 | YouTube kanal banner'ı. Metin 1546×423'lük güvenli alanda — her cihazda görünür. Alt bandaki çayır silueti yalnızca TV'de çıkar. |

Thumbnail köşesinde halkasız versiyon kullanılıyor çünkü video karesinin kendi
çerçevesi zaten var; ikinci bir halka onunla yarışıyor.

## Renkler

| | |
|---|---|
| Koyu zemin | `#16241C` |
| Orta yeşil | `#24503A` |
| Vurgu | `#2F6B45` |
| Krem metin | `#F1F4EE` |
| Soluk metin | `#96B49E` |

## Fontlar

`assets/fonts/` altında, ikisi de OFL (ticari kullanıma açık, atıf zorunlu değil):

- **Bebas Neue** — thumbnail üst satırı, kelime markası
- **Inter SemiBold** — thumbnail alt satırı, slogan

Lisans metinleri aynı klasörde: `OFL-BebasNeue.txt`, `OFL-Inter.txt`.
Bu dosyaları `sources` defterine de işle.
