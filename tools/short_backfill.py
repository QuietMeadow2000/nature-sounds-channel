"""Zaten yayinda olan eski bir video icin, GERIYE DONUK Shorts uret.

GUVENLIK: bu arac ana videoya hicbir zaman dokunmuyor — yeniden yuklemiyor,
history.json'a yazmiyor. Yalnizca o gunun render'ini yerelde (runner'da)
tekrar uretip 45 sn'lik bir dilim kesiyor ve SADECE o dilimi, zaten var olan
video kimligine baglayarak Shorts olarak yukluyor.

    python tools/short_backfill.py --channel config/channel_main.yaml --date 2026-09-06
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from util import history, load_yaml, log, setup_logging, workdir  # noqa: E402
from main import load_secrets  # noqa: E402
import build_audio, build_video, drive, shorts, upload_youtube  # noqa: E402


def entry_for(day: str) -> dict:
    for e in reversed(history()):
        if e.get("date") == day:
            return e
    raise SystemExit(f"history.json'da {day} tarihli kayit yok.")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--channel", default="config/channel_main.yaml")
    ap.add_argument("--date", required=True, metavar="YYYY-MM-DD")
    args = ap.parse_args()
    setup_logging()

    e = entry_for(args.date)
    theme, seed, video_id = e["theme"], int(e["seed"]), e.get("video_id")
    if not video_id:
        raise SystemExit(
            f"{args.date} kaydinda video_id yok — hangi videoya baglanacagini bilemiyorum."
        )
    log.info("Geriye donuk Shorts: %s  tema=%s  ana video=https://youtu.be/%s",
             args.date, theme, video_id)

    cfg = load_yaml(REPO / args.channel)
    secrets = load_secrets()
    for k in ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN"):
        if not secrets.get(k):
            print(f"EKSIK secret: {k}"); return 1

    work = workdir(f"{args.date}-shortonly")
    assets = work / "assets"
    if secrets["GDRIVE_SA_JSON"]:
        drive.sync(theme, secrets["GDRIVE_SA_JSON"], cfg["drive"]["root_folder"],
                  assets, cfg["drive"].get("sources_sheet", "sources"))
    else:
        assets = REPO / "assets"

    audio = build_audio.build(theme, cfg, assets, work, seed)
    video = build_video.build(theme, cfg, assets, work, audio["path"], seed,
                              pexels_key=secrets["PEXELS_API_KEY"] or None)

    clip = work / "short.mp4"
    shorts.extract_clip(video["path"], clip, cfg)
    meta = shorts.build_meta(theme, cfg, e["title"], video_id)
    # Ana video zaten gunlerdir yayinda — Short'u onunla "senkron ac" diye
    # zamanlamanin bir anlami yok (o mantik SADECE aninda uretilen gunun
    # videosu icin gecerli). Burada aninda public yayinliyoruz.
    backfill_cfg = dict(cfg, channel=dict(cfg["channel"], schedule_publish=False))
    short_id = upload_youtube.publish_short(clip, None, meta, backfill_cfg, secrets)
    log.info("Yuklendi: https://youtu.be/%s  (ana video: https://youtu.be/%s)",
             short_id, video_id)
    # history.json'a KASITLI olarak yazmiyoruz — bu bir backfill, gunun
    # normal uretim kaydini kirletmemeli.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
