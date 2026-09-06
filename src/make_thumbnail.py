"""Thumbnail uretimi (Bolum 8): videodan kare + buyuk yazi + kucuk logo.

Fontlar Drive'daki fonts/ klasorunden gelir (Bolum 3.7). Sistem fontuna DUSMEZ:
runner'da Arial/Helvetica yoktur, Pillow sessizce bitmap fonta duser ve thumbnail
okunmaz hale gelir — bu yuzden font eksikse acik hata veriyoruz.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from PIL import Image, ImageDraw, ImageEnhance, ImageFont

from util import PipelineError, ffmpeg, log

MAX_BYTES = 2 * 1024 * 1024          # YouTube thumbnail siniri


def grab_frame(video: Path, out: Path, at_sec: float = 900.0) -> None:
    """Videonun ortalarindan temsili bir kare sec (ffmpeg `thumbnail` filtresi)."""
    ffmpeg(
        ["-ss", f"{at_sec:.1f}", "-i", str(video), "-vf", "thumbnail=100",
         "-frames:v", "1", str(out)],
        "thumbnail karesi",
    )


def _font(assets: Path, rel: str, size: int) -> ImageFont.FreeTypeFont:
    path = assets / rel
    if not path.exists():
        raise PipelineError(
            f"Font yok: {path}\n"
            f"Bolum 3.7 — OFL lisansli .ttf dosyalarini Drive'daki fonts/ klasorune koy."
        )
    return ImageFont.truetype(str(path), size)


def _fit(draw: ImageDraw.ImageDraw, text: str, assets: Path, rel: str,
         max_w: int, start: int) -> Tuple[ImageFont.FreeTypeFont, int, int]:
    """Metni max_w'ye sigacak en buyuk punto ile don."""
    size = start
    while size > 20:
        font = _font(assets, rel, size)
        box = draw.textbbox((0, 0), text, font=font)
        if box[2] - box[0] <= max_w:
            return font, box[2] - box[0], box[3] - box[1]
        size -= 4
    raise PipelineError(f"Metin sigmadi: {text!r}")


def _shadowed(draw: ImageDraw.ImageDraw, xy: Tuple[int, int], text: str,
              font: ImageFont.FreeTypeFont, offset: int = 3) -> None:
    x, y = xy
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

    f_top, w_top, h_top = _fit(draw, top, assets, tcfg["title_font"], max_w, 150)
    f_bot, w_bot, h_bot = _fit(draw, bottom, assets, tcfg["subtitle_font"], max_w, 76)

    gap = int(H * 0.04)
    block_h = h_top + gap + h_bot
    y = (H - block_h) // 2
    _shadowed(draw, ((W - w_top) // 2, y), top, f_top)
    _shadowed(draw, ((W - w_bot) // 2, y + h_top + gap), bottom, f_bot)

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
