"""Manuel yayin modu icin kopyala-yapistir sayfasi (Bolum 10, manuel yol).

API audit onayi gelene kadar video YouTube Studio'ya elle yukleniyor. Bu dosya
Studio'da doldurulacak her alani hazir halde veriyor — baslik, aciklama, etiketler,
ayarlar ve ceviriler. Amac gunluk isi bes dakikanin altinda tutmak.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, Dict

from gen_metadata import LOCALE_NAMES

CATEGORIES = {"10": "Music", "22": "People & Blogs"}


def write(
    out_dir: Path, day: str, theme: str, meta: Dict[str, Any], cfg: Dict[str, Any],
    video_name: str, thumb_name: str,
) -> Path:
    ch = cfg["channel"]
    tcfg = cfg["themes"][theme]
    cat = str(ch["category_id"])
    tags_line = ", ".join(meta["tags"])

    lines = [
        f"{ch['name'].upper()} — {day} — {theme}",
        "=" * 60,
        "",
        "YouTube Studio → Create → Upload videos",
        f"Video dosyasi : {video_name}",
        f"Thumbnail     : {thumb_name}",
        "",
        "-" * 60,
        "BASLIK  (kopyala)",
        "-" * 60,
        meta["title"],
        "",
        "-" * 60,
        "ACIKLAMA  (kopyala)",
        "-" * 60,
        meta["description"],
        "",
        "-" * 60,
        "ETIKETLER  (tek satir, Studio'ya oldugu gibi yapistir)",
        "-" * 60,
        tags_line,
        f"[{len(meta['tags'])} etiket, {len(tags_line)} karakter — sinir 500]",
        "",
        "-" * 60,
        "AYARLAR",
        "-" * 60,
        f"Kategori        : {CATEGORIES.get(cat, cat)}  (Show more → Category)",
        f"Cocuklar icin mi: Hayir  (No, it's not made for kids)",
        f"Playlist        : {tcfg.get('playlist_name', '-')}",
        f"Dil             : {ch.get('language', 'en')}  (Show more → Video language)",
        f"Gorunurluk      : Public",
    ]

    locs = meta.get("localizations") or {}
    if locs:
        lines += [
            "",
            "-" * 60,
            "CEVIRILER  (Studio → Subtitles / Localization → Add language)",
            "-" * 60,
            "Zorunlu degil, ama izleyicinin diline gore gosteriliyor ve erisimi artiriyor.",
        ]
        for code, val in locs.items():
            lines += [
                "",
                f"[{code}] {LOCALE_NAMES.get(code, code)}",
                f"  Baslik   : {val['title']}",
                f"  Aciklama : {val['description']}",
            ]

    lines += [
        "",
        "-" * 60,
        f"Metadata kaynagi: {meta.get('generated_by', '-')}",
        "Bu dosya otomatik uretildi. Audit onayi gelince yukleme de otomatiklesir;",
        "o zaman config'de publish_mode: api yapilir ve bu sayfa uretilmez.",
        "",
    ]

    path = out_dir / f"{day}-{theme}.txt"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
