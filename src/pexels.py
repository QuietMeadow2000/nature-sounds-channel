"""Pexels stok video arama/indirme (Bolum 3.4, 7).

Lisans: ticari kullanim serbest, atif zorunlu degil. Yine de her indirilen dosya
`sources` kayit defterine yazilir (Bolum 16.1) — Content ID itirazlarinda kanit.
"""
from __future__ import annotations

import random
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

API = "https://api.pexels.com/videos/search"
TIMEOUT = 30
MIN_SEC, MAX_SEC = 8, 45
MIN_HEIGHT = 1080


def search(query: str, api_key: str, per_page: int = 30) -> List[Dict[str, Any]]:
    resp = requests.get(
        API,
        headers={"Authorization": api_key},
        params={"query": query, "orientation": "landscape",
                "size": "large", "per_page": per_page},
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json().get("videos", [])


def _best_file(video: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """1080p veya uzeri, en dusuk uygun cozunurluk (gereksiz 4K indirme)."""
    files = [
        f for f in video.get("video_files", [])
        if f.get("height") and f["height"] >= MIN_HEIGHT and f.get("link")
        and (f.get("file_type") or "").endswith("mp4")
    ]
    return min(files, key=lambda f: f["height"]) if files else None


def fetch_video(query: str, api_key: str, work: Path,
                rng: Optional[random.Random] = None) -> Optional[Dict[str, Any]]:
    """Aramadan uygun bir klip indir. Bulunamazsa None (cagiran yedege duser)."""
    rng = rng or random.Random()
    candidates = [
        v for v in search(query, api_key)
        if MIN_SEC <= int(v.get("duration", 0)) <= MAX_SEC and _best_file(v)
    ]
    if not candidates:
        return None

    video = rng.choice(candidates)
    vfile = _best_file(video)
    dst = work / f"pexels_{video['id']}.mp4"

    with requests.get(vfile["link"], stream=True, timeout=TIMEOUT) as resp:
        resp.raise_for_status()
        with dst.open("wb") as fh:
            for chunk in resp.iter_content(chunk_size=1 << 20):
                fh.write(chunk)

    return {
        "kind": "clip",
        "path": dst,
        "source": f"pexels:{video['id']}",
        "credit": {
            "id": video["id"],
            "url": video.get("url"),
            "author": (video.get("user") or {}).get("name"),
            "author_url": (video.get("user") or {}).get("url"),
            "query": query,
            "license": "Pexels License (ticari kullanim serbest)",
            "height": vfile["height"],
        },
    }
