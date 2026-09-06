"""Thumbnail uretimi (Bolum 8): videodan kare + buyuk yazi + kucuk logo.

Fontlar Drive'daki fonts/ klasorunden gelir (Bolum 3.7). Sistem fontuna DUSMEZ:
runner'da Arial/Helvetica yoktur, Pillow sessizce bitmap fonta duser ve thumbnail
okunmaz hale gelir — bu yuzden font eksikse acik hata veriyoruz.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from PIL import Image, ImageDraw, ImageEnhance, ImageFont

from util import PipelineError, duration_sec, ffmpeg, log

MAX_BYTES = 2 * 1024 * 1024          # YouTube thumbnail siniri


def grab_frame(video: Path, out: Path, at_frac: float = 0.4) -> None:
    """Videonun icinden temsili bir kare sec (ffmpeg `thumbnail` filtresi).

    Konum sureden hesaplanir: sabit bir saniye vermek kisa videolarda sessizce
    bos cikti uretir — ffmpeg dosya sonunu asan bir -ss icin 0 donduruyor ama
    hicbir kare yazmiyor. Bu yuzden hem oransal konum hem de acik varlik kontrolu var.
    """
    dur = duration_sec(video, streams="v")
    for at_sec in (dur * at_frac, dur * 0.1, 0.0):
        ffmpeg(
            ["-ss", f"{max(0.0, at_sec):.2f}", "-i", str(video), "-vf", "thumbnail=100",
             "-frames:v", "1", str(out)],
            "thumbnail karesi",
        )
        if out.exists() and out.stat().st_size > 0:
            return
    raise PipelineError(f"{video.name}: thumbnail karesi alinamadi (sure {dur:.1f} sn)")


def _font(assets: Path, rel: str, size: int) -> ImageFont.FreeTypeFont:
    path = assets / rel
    if not path.exists():
        raise PipelineError(
            f"Font yok: {path}\n"
            f"Bolum 3.7 — OFL lisansli .ttf dosyalarini Drive'daki fonts/ klasorune koy."
        )
    return ImageFont.truetype(str(path), size)


def _fit(draw: ImageDraw.ImageDraw, text: str, assets: Path, rel: str,
         max_w: int, start: int) -> Tuple[ImageFont.FreeTypeFont, Tuple[int, int, int, int]]:
    """Metni max_w'ye sigacak en buyuk punto ile don (font, murekkep kutusu)."""
    size = start
    while size > 20:
        font = _font(assets, rel, size)
        box = draw.textbbox((0, 0), text, font=font)
        if box[2] - box[0] <= max_w:
            return font, box
        size -= 4
    raise PipelineError(f"Metin sigmadi: {text!r}")


def _shadowed(draw: ImageDraw.ImageDraw, xy: Tuple[int, int], text: str,
              font: ImageFont.FreeTypeFont, box: Tuple[int, int, int, int],
              offset: int = 3) -> None:
    """xy = MUREKKEBIN sol-ust kosesi.

    draw.text ankraji murekkebin ustu degil, satir kutusunun ustudur — textbbox'in
    (x0, y0) ofseti cikarilmazsa satirlar birbirinin ustune biner.
    """
    x, y = xy[0] - box[0], xy[1] - box[1]
    draw.text((x + offset, y + offset), text, font=font, fill=(0, 0, 0, 170))
    draw.text((x, y), text, font=font, fill=(255, 255, 255, 255))


def build(
    video: Path, theme: str, cfg: Dict[str, Any], assets: Path, work: Path,
    title_line: Optional[str] = None, subtitle_line: Optional[str] = None,
) -> Path:
    tcfg = cfg["thumbnail"]
    W, H = int(tcfg["width"]), int(tcfg["height"])

    frame = work / "frame.png"
    grab_frame(video, frame)

    img = Image.open(frame).convert("RGB").resize((W, H), Image.LANCZOS)
    img = ImageEnhance.Brightness(img).enhance(1.0 - float(tcfg.get("darken", 0.35)))
    img = img.convert("RGBA")

    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    top = (title_line or theme.replace("_", " ") + " sounds").upper()
    purpose = cfg["themes"][theme].get("purpose", "").split(",")[0].strip()
    bottom = (subtitle_line or f"for {purpose}").upper()

    margin = int(W * 0.07)
    max_w = W - 2 * margin

    f_top, b_top = _fit(draw, top, assets, tcfg["title_font"], max_w, 150)
    f_bot, b_bot = _fit(draw, bottom, assets, tcfg["subtitle_font"], max_w, 76)
    w_top, h_top = b_top[2] - b_top[0], b_top[3] - b_top[1]
    w_bot, h_bot = b_bot[2] - b_bot[0], b_bot[3] - b_bot[1]

    gap = int(H * 0.045)
    block_h = h_top + gap + h_bot
    y = (H - block_h) // 2
    _shadowed(draw, ((W - w_top) // 2, y), top, f_top, b_top)
    _shadowed(draw, ((W - w_bot) // 2, y + h_top + gap), bottom, f_bot, b_bot)

    img = Image.alpha_composite(img, overlay)

    logo_path = assets / tcfg.get("logo", "logo.png")
    if logo_path.exists():
        logo = Image.open(logo_path).convert("RGBA")
        lw = int(W * float(tcfg.get("logo_width_pct", 0.08)))
        lh = max(1, int(logo.height * lw / logo.width))
        logo = logo.resize((lw, lh), Image.LANCZOS)
        img.alpha_composite(logo, (W - lw - margin // 2, H - lh - margin // 2))
    else:
        log.warning("Logo yok (%s) — thumbnail logosuz uretildi.", logo_path)

    out = work / "thumb.jpg"
    rgb = img.convert("RGB")
    for quality in (92, 86, 80, 72, 64):
        rgb.save(out, "JPEG", quality=quality, optimize=True, progressive=True)
        if out.stat().st_size <= MAX_BYTES:
            break
    frame.unlink(missing_ok=True)
    log.info("Thumbnail: %s (%.0f KB, %r / %r)", out.name, out.stat().st_size / 1024, top, bottom)
    return out
