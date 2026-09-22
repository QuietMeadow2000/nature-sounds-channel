"""YouTube canli yayin — gunluk video, canli olarak yayinlanip sonra normal
video olarak kanalda kalir (YouTube yayin bitince kendisi arsivliyor).

7/24 SONSUZ DONGU DEGIL, kasitli olarak: gunde bir kez, videonun kendi suresi
kadar (1-3 saat) gercek bir canli yayin aciliyor, bitince kapaniyor. 2026
politikasi ayni kisa klibi sonsuza tekrar eden kanallari hedef aliyor; bizim
zaten 6 Eylul askiya alinmasi da otomasyon deseninden kaynaklanmisti. Gunluk,
sinirli sureli, gercek icerikli yayin o desenden acikca ayrisiyor.

Gereksinim: kanalda "Canli yayin" ozelligi Studio'dan acilmis olmali (API ile
acilamiyor) ve acildiktan ~24 saat sonra kullanilabilir hale geliyor.
"""
from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Any, Dict, Optional

from util import PipelineError, STATE, log, _tool

LIVE_STREAM_ID_FILE = STATE / "live_stream_id.txt"


def _persisted_stream_id() -> Optional[str]:
    if LIVE_STREAM_ID_FILE.exists():
        sid = LIVE_STREAM_ID_FILE.read_text().strip()
        return sid or None
    return None


def ensure_stream(svc, title: str) -> Dict[str, str]:
    """Kalici bir liveStream kaynagi getir ya da olustur.

    Ingestion adresi/anahtari her gun ayni kalsin diye stream KALICI: bir kez
    olusturulup state/live_stream_id.txt'e yaziliyor (repo'ya commit edilir).
    Her gun yeni olan sey liveBroadcast — o bind edilip sonra ayriliyor.
    """
    sid = _persisted_stream_id()
    if sid:
        r = svc.liveStreams().list(part="snippet,cdn,status", id=sid).execute()
        items = r.get("items", [])
        if items:
            cdn = items[0]["cdn"]["ingestionInfo"]
            return {"id": sid, "ingestion_address": cdn["ingestionAddress"],
                    "stream_name": cdn["streamName"]}
        log.warning("Kayitli liveStream (%s) artik bulunamiyor, yenisi olusturuluyor.", sid)

    body = {
        "snippet": {"title": f"{title} — kalici akis"},
        "cdn": {"frameRate": "variable", "resolution": "variable",
                "ingestionType": "rtmp"},
        "contentDetails": {"isReusable": True},
    }
    r = svc.liveStreams().insert(part="snippet,cdn,contentDetails", body=body).execute()
    cdn = r["cdn"]["ingestionInfo"]
    LIVE_STREAM_ID_FILE.write_text(r["id"])
    log.info("Kalici liveStream olusturuldu: %s", r["id"])
    return {"id": r["id"], "ingestion_address": cdn["ingestionAddress"],
            "stream_name": cdn["streamName"]}


def create_and_bind_broadcast(svc, meta: Dict[str, Any], cfg: Dict[str, Any],
                              stream_id: str, scheduled_start_iso: str,
                              synthetic: bool = False) -> str:
    """liveBroadcast olustur ve kalici stream'e bagla. Broadcast ID (= video ID) dondurur."""
    ch = cfg["channel"]
    status: Dict[str, Any] = {
        "privacyStatus": ch["privacy_status"],
        "selfDeclaredMadeForKids": bool(ch.get("made_for_kids", False)),
    }
    if synthetic:
        status["containsSyntheticMedia"] = True

    body = {
        "snippet": {
            "title": meta["title"], "description": meta["description"],
            "scheduledStartTime": scheduled_start_iso,
        },
        "status": status,
        "contentDetails": {
            "enableAutoStart": True,   # RTMP verisi gelince testing->live otomatik
            "enableAutoStop": True,    # akis kesilince otomatik tamamlanir
            "enableDvr": True,
            "recordFromStart": True,
        },
    }
    r = svc.liveBroadcasts().insert(
        part="snippet,status,contentDetails", body=body).execute()
    bid = r["id"]
    svc.liveBroadcasts().bind(id=bid, part="id,contentDetails",
                              streamId=stream_id).execute()
    log.info("Yayin olusturuldu ve baglandi: %s", bid)
    return bid


def push_rtmp(video_path: Path, ingestion_address: str, stream_name: str,
             expected_duration_sec: float) -> None:
    """Videoyu gercek zamanli hizda RTMP'ye akit.

    -c copy: yeniden kodlama yok (build_video zaten 2 sn'lik GOP ile canli
    yayina uygun kodluyor). -re: dosyayi native kare hizinda okuyup gonderir,
    yani 3 saatlik video gercekten 3 saatte gider — bu, "canli" olmanin sarti.
    """
    url = f"{ingestion_address.rstrip('/')}/{stream_name}"
    cmd = [_tool("ffmpeg"), "-hide_banner", "-loglevel", "warning", "-stats",
           "-re", "-i", str(video_path), "-c", "copy",
           "-f", "flv", url]
    log.info("RTMP akisi basliyor (tahmini sure %.0f dk)...", expected_duration_sec / 60)
    t0 = time.time()
    # Guvenlik siniri: beklenenin %20 fazlasi + 10 dk. Donen/kilitlenen bir
    # ffmpeg sureci is'i sonsuza kadar acik tutmasin.
    timeout = expected_duration_sec * 1.2 + 600
    try:
        proc = subprocess.run(cmd, timeout=timeout,
                              capture_output=True, text=True)
    except subprocess.TimeoutExpired:
        raise PipelineError(
            f"RTMP akisi {timeout/60:.0f} dk'da bitmedi, sonlandirildi. "
            f"Beklenen sure {expected_duration_sec/60:.0f} dk idi."
        )
    gecen = time.time() - t0
    if proc.returncode != 0:
        tail = "\n".join(proc.stderr.splitlines()[-25:])
        raise PipelineError(f"RTMP akisi basarisiz (kod {proc.returncode}, "
                            f"{gecen/60:.0f} dk sonra):\n{tail}")
    log.info("RTMP akisi tamamlandi (%.0f dk surdu).", gecen / 60)


def wait_for_status(svc, broadcast_id: str, target: set, timeout_sec: int) -> Optional[str]:
    """Yayinin durumu hedeflerden birine gelene kadar bekle. Gelmezse None."""
    t0 = time.time()
    while time.time() - t0 < timeout_sec:
        r = svc.liveBroadcasts().list(part="status", id=broadcast_id).execute()
        items = r.get("items", [])
        if items:
            durum = items[0]["status"]["lifeCycleStatus"]
            if durum in target:
                return durum
        time.sleep(10)
    return None


def finish_broadcast(svc, broadcast_id: str) -> None:
    """enableAutoStop tamamlamadiysa yayini elle 'complete' durumuna gecir."""
    r = svc.liveBroadcasts().list(part="status", id=broadcast_id).execute()
    items = r.get("items", [])
    if items and items[0]["status"]["lifeCycleStatus"] == "complete":
        return
    log.warning("Otomatik tamamlanmadi, elle 'complete' durumuna geciriliyor.")
    svc.liveBroadcasts().transition(
        broadcastStatus="complete", id=broadcast_id, part="status").execute()
