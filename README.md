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
`sources` defterinde **A sütunu dosya adı** olmalı; defterde olmayan dosya pipeline'a
girmez (`drive.check_registered`).

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
  Yerine saat boyunca çok yavaş renk/parlaklık kayması (tek filtre, maliyetsiz).
- **Metadata maliyeti:** Plan "ayda ~1 $" diyordu; 5 dilde çeviri eklenince
  `claude-opus-5` ile ayda ~2,5 $. `config` içinde `metadata.model: claude-sonnet-5`
  yazarak düşürülebilir.
