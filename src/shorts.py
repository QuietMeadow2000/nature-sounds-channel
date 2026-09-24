"""Uzun formdan 9:16 dikey kisa klip cikar ve ayni gunun videosuyla birlikte
yayinla.

Amac: kesif. Sifir aboneli bir kanalda YouTube'un Shorts akisi, ana video
yuklemekten cok daha genis ve ucuz bir kesif yolu. Maliyeti neredeyse sifir:
render zaten var, sadece kirpip yeniden kodluyoruz (birkac saniye).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from util import duration_sec, ffmpeg, log

CLIP_SEC = 45.0
START_SEC = 90.0   # basin biraz icinden basla — dongu ek yeri/donusler orada olmasin


def extract_clip(source: Path, out: Path, cfg: Dict[str, Any]) -> Path:
    """Yatay videodan 9:16 dikey, kisa bir klip cikar.

    Ortadan kirpip 1080x1920'ye olcekliyoruz — ambient goruntude yuz/aksiyon
    takibi gerekmiyor, merkez kirpma yeterli. -c copy yok: kirpma/olcekleme
    yeniden kodlama gerektiriyor, ama 45 sn'lik klipte maliyeti saniyeler.
    """
    vcfg = cfg["video"]
    total = duration_sec(source, streams="v")
    start = START_SEC if total > START_SEC + 10 else 0.0
    clip_sec = min(CLIP_SEC, max(5.0, total - start - 1))

    vf = "crop=ih*9/16:ih:(iw-ih*9/16)/2:0,scale=1080:1920:flags=lanczos,format=yuv420p"
    ffmpeg([
        "-ss", f"{start:.2f}", "-i", str(source), "-t", f"{clip_sec:.2f}",
        "-vf", vf, "-c:v", "libx264", "-preset", "veryfast",
        "-crf", str(vcfg["crf"]), "-r", str(vcfg["fps"]),
        "-c:a", "aac", "-b:a", "192k",
        str(out),
    ], "shorts klip", out=out)
    log.info("  Shorts klibi: %.0f sn (%.0f-%.0f sn araligi)", clip_sec, start, start + clip_sec)
    return out


def build_meta(theme: str, cfg: Dict[str, Any], parent_title: str,
              parent_video_id: str) -> Dict[str, Any]:
    """Kisa video icin hafif metadata. LLM cagirmiyor — uzun videonun zaten
    (Groq/Claude ile) uretilmis belirli-acili basligindan turetiyor, boylece
    "Rain Sounds" gibi jenerik bir seye geri donmuyor.
    """
    tcfg = cfg["themes"][theme]
    ozel = parent_title.split("|")[0].strip()   # sure kismini (| 3 Hours) at
    title = f"{ozel} #shorts"
    if len(title) > 95:
        title = ozel[:95 - len(" #shorts")] + " #shorts"
    description = (
        f"{ozel}\n\n"
        f"Full video: https://youtu.be/{parent_video_id}\n\n"
        f"#shorts #{theme.replace('_', '')} #naturesounds #ambient #relaxation"
    )
    return {
        "title": title,
        "description": description,
        "tags": ["shorts", theme.replace("_", " "), "nature sounds", "ambient",
                 "relaxation", (tcfg.get("playlist_name") or "").lower()],
        "localizations": {},
        "generated_by": "shorts_template",
    }
