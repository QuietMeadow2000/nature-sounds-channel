# Quiet Meadow — otomatik doğa sesleri kanalı

Her gün 1 saatlik, kesintisiz döngülü doğa sesi videosu üretip YouTube'a yükleyen
pipeline. Tamamen GitHub Actions üzerinde çalışır. Plan: `youtube-doga-sesleri-projesi.md`.

## Hızlı bakış

```
23:17 UTC cron
  → tema seç (ağırlıklı rastgele + sezon takvimi, son 2 temadan farklı)
  → Drive'dan o günün varlıklarını indir
  → ses: kayıtları -18 LUFS'a getir, döngü birimi üret, katmanları farklı
     periyot ve offset'le 60 dk'ya uzat, mikle
  → görsel: AI klip / Pexels / Ken Burns → döngü birimi → 60 dk
  → thumbnail (kare + yazı + logo)
  → metadata: Claude API (başlık, açıklama, etiket, 5 dilde çeviri)
  → YouTube'a yükle, thumbnail ata, playlist'e ekle
  → state/ commit
```

## Ölçülen değerler (yerel, Apple Silicon)

| | |
|---|---|
| 60 dk render, uçtan uca | **2 dk 15 sn** (ses ~80 sn, video ~50 sn) |
| — eski yöntem (karşılaştırma) | 13 dk; runner'da 47 dk |
| Çıktı boyutu | 475–480 MB (plan tahmini 500 MB–1 GB) |
| Ses döngü ek yeri | sıçrama oranı 1,08 (1,0 = kusursuz); kasıtlı bozuk döngüde 2,54 |
| Video döngü ek yeri | oran 1,46 (eşik 2,0) |

**Hızlı render nasıl çalışıyor:** video, döngü biriminin yüzlerce kez tekrarı.
Eskiden 3600 saniyenin tamamı kodlanıyordu çünkü renk kayması her tekrarı farklı
yapıyor ve hiçbiri kopyalanamıyordu. Şimdi kayma parça düzeyine taşındı: birim
12 farklı renk fazında kodlanıp parçalar **yeniden kodlanmadan** birleştiriliyor.
Kodlanan süre 3600 → 347 saniye.

Ölçüldü: varyant geçişi görünmüyor. Döngü ek yerindeki kare farkı 4,91/255 ve bu
değer varyant sınırında da aynı (4,89–4,92) — yani geçiş, videonun zaten var olan
crossfade'inin üstüne ölçülebilir bir şey eklemiyor.

## Kurulum durumu

| Adım | Durum |
|---|---|
| Kod | ✅ hazır |
| GitHub Secrets | ⬜ `YT_CLIENT_ID`, `YT_CLIENT_SECRET`, `YT_REFRESH_TOKEN`, `PEXELS_API_KEY`, `ANTHROPIC_API_KEY`, `GDRIVE_SA_JSON` |
| Drive varlıkları | ⬜ ses / klip / fotoğraf / font / logo |
| Playlist ID'leri | ⬜ `config/channel_main.yaml` içinde boş |
| YouTube API audit | ⬜ onaya kadar `privacy_status: private` |

## Varlık konvansiyonu (Drive)

```
nature-sounds-assets/
├── audio/<tema>/<match>__<kaynak>.flac    # match, config'deki mix.match ile eşleşir
├── clips/<tema>/*.mp4                     # AI klipler
├── photos/<tema>/*.jpg                    # Ken Burns yedeği
├── fonts/*.ttf + OFL.txt                  # OFL lisanslı (Bölüm 3.7)
├── logo.png
└── sources  (Google Sheet)                # kaynak kayıt defteri
```

Dosya adı eşleşmesi: `distant_thunder__freesound_512345.flac` → `match: distant_thunder`.

**Ses dosyalarını FLAC 16-bit / 44,1 kHz olarak sakla.** Freesound'dan inen 24-bit/48 kHz
WAV'lar gereksiz yer kaplıyor — çıktı zaten 192 kbps AAC. Ölçüldü: 237 MB → 81 MB (%34),
duyulur kayıp yok. Gerekçe: en kritik kaydın (uzak gök gürültüsü) kendi zemin gürültüsü
−89,5 dBFS, 16-bit kuantalama gürültüsü −96 dBFS; mikste ikisi de duyulmuyor. 44,1 kHz
ayrıca pipeline'ın hedef hızı, render'da bir yeniden örnekleme adımı eksiliyor.

```bash
ffmpeg -i indirilen.wav -ar 44100 -sample_fmt s16 -c:a flac -compression_level 8 hedef.flac
```

**MP3/AAC dosyalara dokunma** — zaten sıkıştırılmışlar, FLAC'a çevirmek 6 kat büyütüyor
(ölçüldü: 12 MB → 74 MB).
`sources` defterinde **A sütunu dosya adı** olmalı; defterde olmayan dosya pipeline'a
girmez (`drive.check_registered`).

Defter **repo'da** tutuluyor: `state/sources.csv`. Git geçmişi zaman damgalı kanıt
sağlıyor — Content ID itirazında "bu dosyayı ne zaman, nereden, hangi lisansla
aldık" sorusunun cevabı orada. Drive'daki kopya pipeline'ın okuduğu yer:

```bash
python tools/sources_push.py     # CSV'yi Drive'a Google Sheet olarak yükler
```

Yeni ses eklerken önce `state/sources.csv`'ye satır ekle, sonra bu komutu çalıştır.
Drive API yüklerken CSV'yi Sheet'e çeviriyor, Sheets API'ye gerek yok.

## Metadata üretimi

Sağlayıcı sırası: `ANTHROPIC_API_KEY` varsa Claude, yoksa `GROQ_API_KEY` varsa
Groq, o da yoksa şablon. Üçü de aynı JSON şemasını kullanıyor.

Şu an **Groq** (`openai/gpt-oss-120b`) — ücretsiz katman, günde tek istek atıyoruz.
Ölçülen kullanım 1300 girdi / 3700–4900 çıktı token.

İki tuzak, ikisi de yaşandı:
- `max_tokens` düşük olursa beş çeviri bitmeden kesiliyor, JSON yarım kalıyor ve
  Groq şema doğrulamasında **400** veriyor (`missing properties: 'ja'`). 8000 gerekiyor.
- Ücretsiz katmanda dakikada 8000 token sınırı var; art arda istek atarsan **429**.
  Üretimde bağlayıcı değil, ikisi için de yeniden deneme var.

Groq anahtarı `fon-takip` projesiyle **ortak**. O projede yenilenirse burada da
güncellemek gerekir.

## Yayın modu

`config/channel_main.yaml` → `channel.publish_mode`:

| Mod | Ne yapar | Ne gerektirir |
|---|---|---|
| `manual` | Video, thumbnail ve kopyala-yapıştır sayfasını `out/<tarih>/` altına bırakır. Studio'ya elle yüklersin. | YouTube API'ye **hiç** ihtiyaç yok — secret gerekmez |
| `api` *(şu an aktif)* | `videos.insert` ile doğrudan yükler, thumbnail atar, playlist'e ekler, çevirileri yazar | Üç YouTube secret'ı |

**Audit gerekmiyor.** Google'ın dokümanı *"denetimden geçmemiş projelerden yüklenen
videolar private'a kısıtlanır"* diyor ve plan uzun süre buna göre kurgulanmıştı.
6 Eylül 2026'da ölçüldü ve yanlış çıktı: denetimsiz bir projeden `privacyStatus: public`
ile yüklenen video public kaldı (`~/projects/veo-to-youtube`, video `INzkY1mspdc`,
oEmbed HTTP 200). Audit başvurusu kota tavanı için faydalı ama yükleme için gerekli değil.

**Asıl risk OAuth uygulamasının "Testing" modunda kalması** — o modda refresh token
7 günde bir geçersiz olur ve pipeline sessizce durur. Google Cloud → Auth Platform →
Audience → **PUBLISH APP** ile production'a alınmalı.

GitHub Actions'ta manuel mod çıktıyı **artifact** olarak bırakır (Actions → ilgili
çalışma → Artifacts). Yerelde çalıştırırsan dosyalar zaten `out/` altında olur ve
indirmen gerekmez.

## Yerel çalıştırma

```bash
brew install ffmpeg                    # zorunlu
python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt

# Drive olmadan, yerel ./assets klasörüyle:
mkdir -p assets/audio/rain assets/photos/rain assets/fonts
./.venv/bin/python src/main.py --channel config/channel_main.yaml --dry-run --keep-work -v
```

`--dry-run` yüklemez, `--keep-work` ara dosyaları (`work/<tarih>/`) bırakır.
`work/<tarih>/qc_seam.wav` ses ek yerini içeren 30 sn'lik kontrol kesitidir —
ilk haftalarda kulakla dinle, tık duyarsan `crossfade_sec`'i 5→8 yap.

## Yeniden üretim

`state/history.json` her videonun tarifini tutar (tema, dosyalar, kazançlar,
offsetler, tohum, Claude çıktısı, video ID).

```bash
python src/main.py --replay 2026-09-14 --dry-run
```

Aynı varlıklar Drive'da durduğu sürece aynı videoyu üretir. Video dosyalarını
saklamaya gerek yok.

## Acil durdurma

- `state/PAUSE` adında boş dosya oluştur (GitHub'da "Add file") → pipeline başlar ve çıkar.
- Ya da Actions → workflow → "Disable workflow".

## Kurulum günü doğrulanacaklar

1. **`containsSyntheticMedia`** — `src/upload_youtube.py` içindeki AI içerik beyanı
   alan adı; YouTube bunu geçmişte yeniden adlandırdı. Yanlış alan 400 döndürür.
   İlk test yüklemesi bunu ortaya çıkarır.
2. **OAuth consent screen "In production"** — "Testing" modunda refresh token 7 günde
   bir düşer.
3. **AI klip araçlarının ücretsiz katmanı** — filigran ve ticari kullanım durumu
   (plan Bölüm 7.1); sık değişiyor.
4. **Claude model adı ve fiyatı** — `src/gen_metadata.py` içindeki `DEFAULT_MODEL`.

## Plandan sapmalar

- **Kaynak defterine yazma:** Plan 16.1 Pexels kayıtlarının Drive'daki Sheet'e
  yazılmasını öngörüyordu, ama 3.8 service account'a yalnızca Viewer veriyor —
  çelişki. Çözüm: otomatik inen varlıklar `state/sources_auto.jsonl`'a yazılıyor ve
  her gün commit'leniyor. Git geçmişi zaman damgalı kanıt sağlıyor, service account
  salt okunur kalıyor, Sheets API'ye gerek kalmıyor.
- **Ping-pong görsel döngü:** Plan 7'de geçiyordu; ffmpeg `reverse` filtresi tüm
  kareleri RAM'de tutuyor (1080p'de GB'larca), runner'ı riske atıyor. Yerine ses
  tarafıyla aynı xfade yöntemi kullanıldı.
- **Tekrar başına görsel varyasyon:** 60 dk benzersiz video render etmek gerekirdi.
  Yerine saat boyunca çok yavaş renk/parlaklık kayması (`video.drift`, tek filtre).
  Ölçüldü: aynı döngü fazındaki iki kare 300 sn arayla ortalama 3,6/255 farklı —
  yani 288 tekrar birbirinin bit-bit kopyası değil. Ardışık kareler arası katkı
  1,1/255, kaynağın kendi hareketi (5 sn'de 24,4/255) yanında görünmez. Dosya
  boyutuna etkisi ölçülemedi (60 dk: 475 MB → 480 MB).
  İki tuzak: `hue=h=` **derece** cinsinden (küçük değerler H.264'te tamamen kaybolur)
  ve `eq` varsayılan olarak ifadeyi bir kez hesaplar — `eval=frame` şart.
- **Metadata maliyeti:** Plan "ayda ~1 $" diyordu; 5 dilde çeviri eklenince
  `claude-opus-5` ile ayda ~2,5 $. `config` içinde `metadata.model: claude-sonnet-5`
  yazarak düşürülebilir.
