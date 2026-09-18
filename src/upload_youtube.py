"""YouTube yukleme (Bolum 10): video, thumbnail, playlist, ceviriler.

Kota (Bolum 3.3/6): videos.insert ~1600, thumbnails.set ~50, playlistItems.insert ~50,
videos.update ~50 birim. Gunluk toplam ~1750 / 10.000.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import random
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from util import PipelineError, log

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]
TOKEN_URI = "https://oauth2.googleapis.com/token"
CHUNK = 8 * 1024 * 1024
RETRIABLE_STATUS = (500, 502, 503, 504)


def client(client_id: str, client_secret: str, refresh_token: str, service: str = "youtube"):
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    if not all([client_id, client_secret, refresh_token]):
        raise PipelineError(
            "YouTube kimlik bilgileri eksik. GitHub Secrets: "
            "YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN (Bolum 3.10)."
        )
    creds = Credentials(
        token=None, refresh_token=refresh_token, token_uri=TOKEN_URI,
        client_id=client_id, client_secret=client_secret, scopes=SCOPES,
    )
    version = "v2" if service == "youtubeAnalytics" else "v3"
    return build(service, version, credentials=creds, cache_discovery=False)


def _publish_at(ch: Dict[str, Any]) -> Optional[str]:
    """Bir sonraki yayin ani (RFC3339 UTC) ya da zamanlama kapaliysa None."""
    if not ch.get("schedule_publish"):
        return None
    saat = str(ch.get("publish_time_utc", "00:00"))
    try:
        sa, dk = (int(x) for x in saat.split(":"))
    except ValueError:
        log.warning("publish_time_utc okunamadi (%r) — zamanlama atlandi.", saat)
        return None
    simdi = datetime.now(timezone.utc)
    hedef = simdi.replace(hour=sa, minute=dk, second=0, microsecond=0)
    # En az 15 dakika sonrasi olmali: yukleme + islenme suresi gerekiyor,
    # gecmis bir publishAt'i YouTube reddediyor.
    while hedef <= simdi + timedelta(minutes=15):
        hedef += timedelta(days=1)
    return hedef.strftime("%Y-%m-%dT%H:%M:%SZ")


def _body(meta: Dict[str, Any], cfg: Dict[str, Any], synthetic: bool) -> Dict[str, Any]:
    ch = cfg["channel"]
    status: Dict[str, Any] = {
        "privacyStatus": ch["privacy_status"],
        "selfDeclaredMadeForKids": bool(ch.get("made_for_kids", False)),
    }
    # Zamanlanmis yayin: video private olarak yuklenir, publishAt'te kendiliginden
    # acilir. Iki faydasi var — icerik aninda yayina dusmuyor, ve acilmadan once
    # gozden gecirilebiliyor. YouTube publishAt'i YALNIZCA privacyStatus private
    # iken kabul ediyor; public ile gonderirsen sessizce yok sayiyor.
    when = _publish_at(ch)
    if when:
        status["privacyStatus"] = "private"
        status["publishAt"] = when
    if synthetic:
        # Bolum 11 — AI gorsel kullanildiginda "altered or synthetic content" beyani.
        # NOT: alan adini kurulum gunu API dokumantasyonundan dogrula; YouTube bu
        # beyani zaman zaman yeniden adlandirdi. Yanlis alan 400 dondurur.
        status["containsSyntheticMedia"] = True
    return {
        "snippet": {
            "title": meta["title"],
            "description": meta["description"],
            "tags": meta["tags"],
            "categoryId": str(ch["category_id"]),
            "defaultLanguage": ch.get("language", "en"),
            "defaultAudioLanguage": ch.get("language", "en"),
        },
        "status": status,
    }


def upload_video(
    yt, video: Path, meta: Dict[str, Any], cfg: Dict[str, Any],
    synthetic: bool = False, attempts: int = 3, backoff_min: int = 20,
) -> str:
    """Resumable yukleme. Gecici hatalarda tekrar dener (Bolum 16.8)."""
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaFileUpload

    last: Optional[Exception] = None
    for attempt in range(1, attempts + 1):
        try:
            media = MediaFileUpload(str(video), chunksize=CHUNK, resumable=True,
                                    mimetype="video/mp4")
            request = yt.videos().insert(
                part="snippet,status", body=_body(meta, cfg, synthetic), media_body=media,
            )
            response, progress = None, 0
            while response is None:
                status, response = request.next_chunk()
                if status and int(status.progress() * 100) >= progress + 20:
                    progress = int(status.progress() * 100)
                    log.info("  yukleniyor... %d%%", progress)
            video_id = response["id"]
            log.info("Yuklendi: https://youtu.be/%s (%s)", video_id,
                     cfg["channel"]["privacy_status"])
            return video_id

        except HttpError as exc:
            status_code = getattr(exc.resp, "status", None)
            if status_code == 403 and "quota" in str(exc).lower():
                raise PipelineError(
                    "YouTube gunluk kotasi doldu (Bolum 15). Ertesi gun kendiliginden duzelir."
                ) from exc
            if status_code not in RETRIABLE_STATUS:
                raise PipelineError(f"YouTube yukleme hatasi ({status_code}): {exc}") from exc
            last = exc
        except OSError as exc:                      # ag kopmasi
            last = exc

        if attempt < attempts:
            wait = backoff_min * 60 + random.randint(0, 60)
            log.warning("Yukleme basarisiz (%s). %d dk sonra tekrar (%d/%d).",
                        last, wait // 60, attempt, attempts)
            time.sleep(wait)

    raise PipelineError(f"Yukleme {attempts} denemede basarisiz: {last}")


def set_thumbnail(yt, video_id: str, thumb: Path) -> None:
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaFileUpload

    try:
        yt.thumbnails().set(
            videoId=video_id,
            media_body=MediaFileUpload(str(thumb), mimetype="image/jpeg"),
        ).execute()
        log.info("Thumbnail atandi")
    except HttpError as exc:
        # Thumbnail hakki dogrulanmamis kanalda yok — videoyu iptal ettirmeye degmez.
        log.warning("Thumbnail atanamadi: %s", exc)


def add_to_playlist(yt, video_id: str, playlist_id: str) -> None:
    from googleapiclient.errors import HttpError

    if not playlist_id:
        log.warning("Playlist ID bos — video playlist'e eklenmedi (config/channel_*.yaml).")
        return
    try:
        yt.playlistItems().insert(
            part="snippet",
            body={"snippet": {
                "playlistId": playlist_id,
                "resourceId": {"kind": "youtube#video", "videoId": video_id},
            }},
        ).execute()
        log.info("Playlist'e eklendi: %s", playlist_id)
    except HttpError as exc:
        log.warning("Playlist'e eklenemedi: %s", exc)


def set_localizations(yt, video_id: str, meta: Dict[str, Any], cfg: Dict[str, Any]) -> None:
    """Bolum 16.3 — YouTube izleyicinin diline gore basligi/aciklamayi gosterir."""
    from googleapiclient.errors import HttpError

    locs = meta.get("localizations") or {}
    if not locs:
        return
    body = {
        "id": video_id,
        "snippet": {
            "title": meta["title"],
            "description": meta["description"],
            "tags": meta["tags"],
            "categoryId": str(cfg["channel"]["category_id"]),
            "defaultLanguage": cfg["channel"].get("language", "en"),
        },
        "localizations": {
            code: {"title": val["title"], "description": val["description"]}
            for code, val in locs.items()
        },
    }
    try:
        yt.videos().update(part="snippet,localizations", body=body).execute()
        log.info("Ceviriler eklendi: %s", ", ".join(sorted(locs)))
    except HttpError as exc:
        log.warning("Ceviriler eklenemedi: %s", exc)


def publish(
    video: Path, thumb: Optional[Path], meta: Dict[str, Any], cfg: Dict[str, Any],
    theme: str, secrets: Dict[str, str], synthetic: bool = False,
) -> str:
    yt = client(secrets.get("YT_CLIENT_ID", ""), secrets.get("YT_CLIENT_SECRET", ""),
                secrets.get("YT_REFRESH_TOKEN", ""))
    rcfg = cfg.get("retry", {})
    video_id = upload_video(
        yt, video, meta, cfg, synthetic,
        attempts=int(rcfg.get("upload_attempts", 3)),
        backoff_min=int(rcfg.get("upload_backoff_min", 20)),
    )
    if thumb and thumb.exists():
        set_thumbnail(yt, video_id, thumb)
    add_to_playlist(yt, video_id, cfg["themes"][theme].get("playlist_id", ""))
    set_localizations(yt, video_id, meta, cfg)
    return video_id
