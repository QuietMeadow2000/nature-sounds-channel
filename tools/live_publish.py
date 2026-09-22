"""Gunun temasini uret ve canli yayin olarak YouTube'a akit.

Ayri, henuz otomatiklestirilmemis bir yol — daily.yml'e bilerek baglanmadi.
Bir kac kez elle test edilip guvenilir oldugu gorulunce gece cron'una
eklenebilir (Bolum 18'de tasarlandigi gibi).

Video zaten olusturduğumuz renderin AYNISI (build_audio + build_video +
gen_metadata + make_thumbnail); tek fark son adim: videos.insert yerine
liveBroadcast olusturup ayni dosyayi RTMP'ye gercek zamanli akitmak.
Yayin bitince YouTube onu otomatik olarak normal, izlenebilir bir video
haline getiriyor — ayrica yuklemeye gerek yok.

    python tools/live_publish.py --channel config/channel_main.yaml [--date YYYY-MM-DD]
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from util import duration_sec, load_yaml, log, setup_logging, workdir  # noqa: E402
import build_audio, build_video, drive, gen_metadata  # noqa: E402
import live_stream, make_thumbnail, pick_theme, upload_youtube  # noqa: E402
# seed_for/load_secrets main.py'de tanimli, burada kopyalamiyoruz.
from main import load_secrets, seed_for  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--channel", default="config/channel_main.yaml")
    ap.add_argument("--date", help="uretim tarihi (YYYY-MM-DD); bos = bugun")
    ap.add_argument("--theme", help="tema elle sec (test icin)")
    ap.add_argument("--start-in-min", type=int, default=3,
                    help="yayinin kac dk sonra baslayacagi (ffmpeg'in baslamasi icin pay)")
    args = ap.parse_args()
    setup_logging()

    cfg = load_yaml(REPO / args.channel)
    channel_key = cfg["channel"].get("key", "main")
    secrets = load_secrets()
    for k in ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN"):
        if not secrets.get(k):
            print(f"EKSIK secret: {k}"); return 1

    today = date.fromisoformat(args.date) if args.date else date.today()
    day = today.isoformat()
    seed = seed_for(day, channel_key)

    if args.theme:
        theme, season_hint = args.theme, None
    else:
        theme, info = pick_theme.pick(cfg, today, seed)
        season_hint = info.get("title_hint")
    log.info("Tema: %s", theme)

    work = workdir(day)
    assets = work / "assets"
    if secrets["GDRIVE_SA_JSON"]:
        registry = drive.sync(theme, secrets["GDRIVE_SA_JSON"], cfg["drive"]["root_folder"],
                              assets, cfg["drive"].get("sources_sheet", "sources"))
    else:
        assets, registry = REPO / "assets", set()

    audio = build_audio.build(theme, cfg, assets, work, seed)
    video = build_video.build(theme, cfg, assets, work, audio["path"], seed,
                              pexels_key=secrets["PEXELS_API_KEY"] or None)
    meta = gen_metadata.generate(theme, cfg, audio["recipe"], video["recipe"],
                                 season_hint, api_key=secrets["ANTHROPIC_API_KEY"] or None)
    try:
        thumb = make_thumbnail.build(video["path"], theme, cfg, assets, work)
    except Exception as exc:
        log.warning("Thumbnail uretilemedi: %s", exc)
        thumb = None

    svc = upload_youtube.client(secrets["YT_CLIENT_ID"], secrets["YT_CLIENT_SECRET"],
                                secrets["YT_REFRESH_TOKEN"])

    stream = live_stream.ensure_stream(svc, cfg["channel"]["name"])
    start_at = (datetime.now(timezone.utc) + timedelta(minutes=args.start_in_min)
               ).strftime("%Y-%m-%dT%H:%M:%SZ")
    synthetic = (video["recipe"]["visual_kind"] == "clip"
                and not video["recipe"]["visual_source"].startswith("pexels:"))
    broadcast_id = live_stream.create_and_bind_broadcast(
        svc, meta, cfg, stream["id"], start_at, synthetic=synthetic)

    if thumb:
        try:
            upload_youtube.set_thumbnail(svc, broadcast_id, thumb)
        except Exception as exc:
            log.warning("Thumbnail atanamadi: %s", exc)

    dur = duration_sec(video["path"], streams="a")
    log.info("Yayin ~%s'de baslayacak: https://youtu.be/%s", start_at, broadcast_id)
    live_stream.push_rtmp(video["path"], stream["ingestion_address"],
                          stream["stream_name"], dur)

    durum = live_stream.wait_for_status(svc, broadcast_id, {"complete"}, timeout_sec=300)
    if not durum:
        live_stream.finish_broadcast(svc, broadcast_id)

    log.info("Bitti: https://youtu.be/%s", broadcast_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
