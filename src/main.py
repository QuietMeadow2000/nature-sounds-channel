"""Gunluk pipeline — tum adimlari sirayla calistirir (Bolum 2).

Kullanim:
    python src/main.py --channel config/channel_main.yaml
    python src/main.py --channel config/channel_test.yaml --dry-run   # yuklemeden
    python src/main.py --replay 2026-09-14                            # ayni videoyu yeniden uret
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sys
import time
import traceback
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

import build_audio
import guards
import build_video
import drive
import gen_metadata
import make_thumbnail
import pick_theme
import publish_sheet
import upload_youtube
from util import (
    OUT, REPO, WORK, PipelineError, append_history, check_disk, clean_work, history,
    load_yaml, log, log_error, paused, setup_logging, workdir,
)

SECRET_NAMES = (
    "YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN",
    "PEXELS_API_KEY", "ANTHROPIC_API_KEY", "GDRIVE_SA_JSON",
)


def seed_for(day: str, channel_key: str) -> int:
    """Gune ve kanala bagli, tekrar uretilebilir tohum (Bolum 16.5)."""
    digest = hashlib.sha256(f"{channel_key}:{day}".encode()).hexdigest()
    return int(digest[:12], 16)


def load_secrets() -> Dict[str, str]:
    return {name: os.environ.get(name, "").strip() for name in SECRET_NAMES}


def replay_entry(day: str) -> Dict[str, Any]:
    for entry in reversed(history()):
        if entry.get("date") == day:
            return entry
    raise PipelineError(f"history.json icinde {day} tarihli kayit yok.")


def run(cfg_path: Path, dry_run: bool, replay: Optional[str], keep_work: bool,
        force_theme: Optional[str] = None, manual: bool = False) -> int:
    cfg = load_yaml(cfg_path)
    channel_key = cfg["channel"].get("key", "main")
    secrets = load_secrets()

    today = date.today()
    day = replay or today.isoformat()
    seed = seed_for(day, channel_key)

    if replay:
        past = replay_entry(replay)
        theme, season_hint = past["theme"], past.get("season_hint")
        seed = int(past.get("seed", seed))
        log.info("REPLAY %s — tema %s, tohum %d", replay, theme, seed)
    elif force_theme:
        if force_theme not in cfg["themes"]:
            raise PipelineError(f"Bilinmeyen tema: {force_theme}")
        theme, season_hint = force_theme, None
        log.info("Tema elle secildi: %s", theme)
    else:
        theme, info = pick_theme.pick(cfg, today, seed)
        season_hint = info.get("title_hint")

    check_disk(float(cfg["audio"]["duration_min"]))

    work = workdir(day)
    assets = work / "assets"

    # 1) Varliklari indir + kaynak defterini oku (Bolum 3.8, 16.1)
    if secrets["GDRIVE_SA_JSON"]:
        registry = drive.sync(
            theme, secrets["GDRIVE_SA_JSON"], cfg["drive"]["root_folder"],
            assets, cfg["drive"].get("sources_sheet", "sources"),
        )
    else:
        local = REPO / "assets"
        if not local.is_dir():
            raise PipelineError(
                "GDRIVE_SA_JSON yok ve yerel ./assets klasoru de yok.\n"
                "Yerel test icin: assets/audio/<tema>/, assets/photos/<tema>/, assets/fonts/"
            )
        assets, registry = local, set()
        log.info("Drive atlandi — yerel varliklar: %s", assets)

    # 2-4) Ses, gorsel, birlestirme
    audio = build_audio.build(theme, cfg, assets, work, seed)
    video = build_video.build(
        theme, cfg, assets, work, audio["path"], seed,
        pexels_key=secrets["PEXELS_API_KEY"] or None,
    )

    used = [l["source"] for l in audio["recipe"]["layers"]] + [video["recipe"]["visual_source"]]
    drive.check_registered(used, registry)
    if video["recipe"]["visual_source"].startswith("pexels:"):
        drive.note_auto_source({
            "date": day, "theme": theme, "asset": video["recipe"]["visual_source"],
            "license": "Pexels License (ticari kullanim serbest)",
        })

    # 5) Thumbnail
    try:
        thumb = make_thumbnail.build(video["path"], theme, cfg, assets, work)
    except PipelineError as exc:
        log.warning("Thumbnail uretilemedi: %s", exc)
        thumb = None

    # 6) Metadata
    meta = gen_metadata.generate(
        theme, cfg, audio["recipe"], video["recipe"], season_hint,
        api_key=secrets["ANTHROPIC_API_KEY"] or None,
    )

    # 7) Yayin
    #    manual : dosyalari out/ altina koyar, Studio'ya elle yuklersin
    #    api    : videos.insert ile dogrudan yukler
    mode = "manual" if manual else cfg["channel"].get("publish_mode", "api")

    # Yayin hizi korumasi (9 Eylul 2026 askiya alinmasindan sonra). Sinir asilmissa
    # video yine uretilir, sadece otomatik yuklenmez — manuel moda duser.
    if mode == "api" and not dry_run:
        svc_guard = None
        try:
            if all(secrets[k] for k in ("YT_CLIENT_ID", "YT_CLIENT_SECRET",
                                        "YT_REFRESH_TOKEN")):
                svc_guard = upload_youtube.client(
                    secrets["YT_CLIENT_ID"], secrets["YT_CLIENT_SECRET"],
                    secrets["YT_REFRESH_TOKEN"])
        except Exception as exc:
            log.warning("Koruma icin kanal bilgisi alinamadi (%s).", type(exc).__name__)
        izin, gerekce = guards.may_publish(cfg, svc_guard)
        if not izin:
            log.warning("Otomatik yayin engellendi — %s. Manuel moda dusuluyor.", gerekce)
            mode = "manual"

    video_id = None
    bundle = None

    if dry_run:
        log.info("DRY RUN — yayin adimi atlandi. Dosyalar: %s", work)
    elif mode == "manual":
        bundle = OUT / day
        bundle.mkdir(parents=True, exist_ok=True)
        stem = f"{day}-{theme}"
        video_name, thumb_name = f"{stem}.mp4", f"{stem}.jpg"
        shutil.copy2(video["path"], bundle / video_name)
        if thumb and thumb.exists():
            shutil.copy2(thumb, bundle / thumb_name)
        sheet = publish_sheet.write(
            bundle, day, theme, meta, cfg, video_name, thumb_name if thumb else "-")
        log.info("MANUEL YAYIN — dosyalar hazir: %s", bundle)
        log.info("  %-28s %.0f MB", video_name, (bundle / video_name).stat().st_size / 1e6)
        log.info("  %-28s kopyala-yapistir sayfasi", sheet.name)
    else:
        bekle = guards.publish_jitter(cfg, rng)
        if bekle:
            log.info("Yayin oncesi %d dk %d sn bekleniyor — cron her gece ayni "
                     "saniyede tetikleniyor, kayma makine desenini kiriyor.",
                     bekle // 60, bekle % 60)
            time.sleep(bekle)

        video_id = upload_youtube.publish(
            video["path"], thumb, meta, cfg, theme, secrets,
            synthetic=video["recipe"]["visual_kind"] == "clip"
            and not video["recipe"]["visual_source"].startswith("pexels:"),
        )

    # 8) Kayit (Bolum 16.5 — bu kayit videoyu birebir yeniden uretmeye yeter)
    # Dry-run YAZMAZ: yuklenmemis bir video "son 2 tema" kuralini ve "son 10 baslik"
    # listesini kirletir, sonraki gercek calismalarin secimini bozardi.
    if replay:
        log.info("REPLAY — history.json'a yazilmadi.")
    elif dry_run:
        log.info("DRY RUN — history.json'a yazilmadi.")
    else:
        append_history({
            "date": day,
            "channel": channel_key,
            "theme": theme,
            "season_hint": season_hint,
            "seed": seed,
            "title": meta["title"],
            "tags": meta["tags"],
            "metadata_by": meta.get("generated_by"),
            "audio": audio["recipe"],
            "video": video["recipe"],
            "video_id": video_id,
            "publish_mode": mode,
            "privacy": cfg["channel"]["privacy_status"] if mode == "api" else "manual",
            "uploaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        })

    if not keep_work and not dry_run:
        clean_work()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Quiet Meadow gunluk pipeline")
    parser.add_argument("--channel", default="config/channel_main.yaml")
    parser.add_argument("--dry-run", action="store_true", help="uretir ama yuklemez")
    parser.add_argument("--replay", metavar="YYYY-MM-DD", help="gecmis bir videoyu yeniden uret")
    parser.add_argument("--theme", help="tema secimini atla (test/hata ayiklama)")
    parser.add_argument("--manual", action="store_true",
                        help="yuklemeden, dosyalari out/<tarih>/ altina birak")
    parser.add_argument("--ignore-pause", action="store_true",
                        help="state/PAUSE varken de calistir (bilincli yerel calistirma)")
    parser.add_argument("--keep-work", action="store_true", help="ara dosyalari silme")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    setup_logging(args.verbose)

    # PAUSE otomatik calismalari durdurur. Yerelde bilincli calistirirken
    # --ignore-pause ile gecilir; bayrak yine de yerinde kalir.
    if paused() and not args.ignore_pause:
        log.warning("state/PAUSE var — pipeline durduruldu (Bolum 16.7). "
                    "Bilincli calistirma icin: --ignore-pause")
        return 0
    if paused():
        log.warning("state/PAUSE var ama --ignore-pause verildi, devam ediliyor.")

    cfg_path = REPO / args.channel if not Path(args.channel).is_absolute() else Path(args.channel)
    try:
        return run(cfg_path, args.dry_run, args.replay, args.keep_work,
                   args.theme, args.manual)
    except PipelineError as exc:
        log.error("%s", exc)
        log_error(str(exc).replace("\n", " | "))
        return 1
    except Exception as exc:                        # beklenmeyen — izi de kaydet
        log.error("Beklenmeyen hata: %s", exc)
        log_error(f"UNEXPECTED {exc!r}")
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
