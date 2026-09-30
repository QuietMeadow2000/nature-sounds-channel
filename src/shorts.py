"""Uzun formdan 9:16 dikey kisa klip cikar ve ayni gunun videosuyla birlikte
yayinla.

Amac: kesif. Sifir aboneli bir kanalda YouTube'un Shorts akisi, ana video
yuklemekten cok daha genis ve ucuz bir kesif yolu. Maliyeti neredeyse sifir:
render zaten var, sadece kirpip yeniden kodluyoruz (birkac saniye).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from util import REPO, duration_sec, ffmpeg, log

CLIP_SEC = 45.0
START_SEC = 90.0   # basin biraz icinden basla — dongu ek yeri/donusler orada olmasin

FONT_TOP = REPO / "assets" / "fonts" / "BebasNeue-Regular.ttf"
FONT_BOTTOM = REPO / "assets" / "fonts" / "Inter-SemiBold.ttf"


def _dtext(text: str) -> str:
    """ffmpeg drawtext icin metni kac: : ' % ozel karakterler grafigi bozuyor."""
    return (text.replace("\\", "\\\\").replace(":", "\\:")
            .replace("'", "\\'").replace("%", "\\%"))


def _caption_filter(top: str, bottom: str) -> str:
    """Kisayi acanin video icinde gordugu tek sey aciklama degil — Shorts'ta
    kimse 'daha fazla'ya dokunup aciklamayi okumuyor. Cagri, piksellerin
    icinde olmak zorunda. Thumbnail ile ayni stil: beyaz metin + yumusak
    siyah golge (make_thumbnail.py'deki draw.text golge deseniyle tutarli).

    Konumlar: y=140 ust guvenli bolge (Shorts'un ust ilerleme cubugunun
    altinda). y=h-360 alt metin icin — Shorts UI'i (begeni/yorum/paylas,
    kullanici adi, aciklama basi) ekranin alt ~%15-18'ini kapladigi icin
    oradan acikca uzak tutuluyor.
    """
    top_t, bot_t = _dtext(top.upper()), _dtext(bottom.upper())
    parcalar = [
        f"drawtext=fontfile='{FONT_TOP}':text='{top_t}':fontsize=72:"
        f"fontcolor=black@0.65:x=(w-text_w)/2+3:y=143",
        f"drawtext=fontfile='{FONT_TOP}':text='{top_t}':fontsize=72:"
        f"fontcolor=white:x=(w-text_w)/2:y=140",
        f"drawtext=fontfile='{FONT_BOTTOM}':text='{bot_t}':fontsize=44:"
        f"fontcolor=black@0.65:x=(w-text_w)/2+2:y=h-358",
        f"drawtext=fontfile='{FONT_BOTTOM}':text='{bot_t}':fontsize=44:"
        f"fontcolor=white:x=(w-text_w)/2:y=h-360",
    ]
    return ",".join(parcalar)


def extract_clip(source: Path, out: Path, cfg: Dict[str, Any],
                 top_text: Optional[str] = None, bottom_text: Optional[str] = None) -> Path:
    """Yatay videodan 9:16 dikey, kisa bir klip cikar.

    Ortadan kirpip 1080x1920'ye olcekliyoruz — ambient goruntude yuz/aksiyon
    takibi gerekmiyor, merkez kirpma yeterli. -c copy yok: kirpma/olcekleme
    yeniden kodlama gerektiriyor, ama 45 sn'lik klipte maliyeti saniyeler.

    top_text/bottom_text verilirse videonun ustune yaziliyor. Sebep olculdu:
    Shorts izlenmeleri (3-6) ana videoya (0-1) hic gecmiyordu — aciklamadaki
    duz metin link Shorts'ta TIKLANMIYOR (YouTube'un kendi kurali, spam
    onlemi) ve kimse 'daha fazla'ya dokunup okumuyor. Cagri piksellerin
    icinde olmali. Metin, y=140 (ust guvenli bolge) ve y=h-360 (Shorts'un
    kendi UI'i — begeni/yorum/paylas, kullanici adi — alt ~%15'i kapladigi
    icin oradan uzak) konumlandi.
    """
    vcfg = cfg["video"]
    total = duration_sec(source, streams="v")
    start = START_SEC if total > START_SEC + 10 else 0.0
    clip_sec = min(CLIP_SEC, max(5.0, total - start - 1))

    vf = "crop=ih*9/16:ih:(iw-ih*9/16)/2:0,scale=1080:1920:flags=lanczos,format=yuv420p"
    if top_text or bottom_text:
        vf += "," + _caption_filter(top_text or "", bottom_text or "")
    ffmpeg([
        "-ss", f"{start:.2f}", "-i", str(source), "-t", f"{clip_sec:.2f}",
        "-vf", vf, "-c:v", "libx264", "-preset", "veryfast",
        "-crf", str(vcfg["crf"]), "-r", str(vcfg["fps"]),
        "-c:a", "aac", "-b:a", "192k",
        str(out),
    ], "shorts klip", out=out)
    log.info("  Shorts klibi: %.0f sn (%.0f-%.0f sn araligi)", clip_sec, start, start + clip_sec)
    return out


def _duration_word(parent_title: str) -> str:
    """Basliktaki '| 3 Hours' kismindan sureyi cikar, yoksa varsayilan."""
    if "|" in parent_title:
        kuyruk = parent_title.split("|")[-1].strip()
        if kuyruk:
            return kuyruk
    return "Full Video"


def build_meta(theme: str, cfg: Dict[str, Any], parent_title: str,
              parent_video_id: str) -> Dict[str, Any]:
    """Kisa video icin hafif metadata. LLM cagirmiyor — uzun videonun zaten
    (Groq/Claude ile) uretilmis belirli-acili basligindan turetiyor, boylece
    "Rain Sounds" gibi jenerik bir seye geri donmuyor.

    caption_top/caption_bottom: videonun icine yakilacak metin (bkz.
    extract_clip). comment_text: kanal sahibi olarak birakilacak yorum —
    Shorts'ta aciklamadaki link tiklanmadigi icin bu, gercek tiklanabilir
    tek yer.
    """
    tcfg = cfg["themes"][theme]
    ozel = parent_title.split("|")[0].strip()   # sure kismini (| 3 Hours) at
    sure = _duration_word(parent_title)
    title = f"{ozel} #shorts"
    if len(title) > 95:
        title = ozel[:95 - len(" #shorts")] + " #shorts"
    description = (
        f"{ozel}\n\n"
        f"Full video ({sure}): https://youtu.be/{parent_video_id}\n\n"
        f"#shorts #{theme.replace('_', '')} #naturesounds #ambient #relaxation"
    )
    return {
        "title": title,
        "description": description,
        "tags": ["shorts", theme.replace("_", " "), "nature sounds", "ambient",
                 "relaxation", (tcfg.get("playlist_name") or "").lower()],
        "localizations": {},
        "generated_by": "shorts_template",
        "caption_top": ozel,
        # DOGRULANDI: Shorts'ta aciklama/yorum icindeki hicbir link tiklanmiyor
        # (spam onlemi, pekistirilmis yorum dahil). Tek gercek tek-dokunuslu
        # eylem ekranda zaten duran KANAL ADI/avatari. Cagri o yuzden "linke
        # tikla" degil, "kanal adina dokun / abone ol" olmali.
        "caption_bottom": f"{sure} Version — Tap Channel Name",
        "comment_text": (
            f"The full {sure.lower()} version is on this channel \U0001f3b6 "
            f"(tap the channel name above)"
        ),
    }
