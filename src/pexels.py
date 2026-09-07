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


def _download(video: Dict[str, Any], query: str, work: Path) -> Dict[str, Any]:
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


def fetch_candidates(query: str, api_key: str, work: Path,
                     rng: Optional[random.Random] = None,
                     count: int = 3) -> List[Dict[str, Any]]:
    """Birkac uygun klip indir. Cagiran aralarindan en az hareketlisini secer.

    Tek klip indirip kabul etmek riskli: drone/kaydirmali cekimler hem dongude
    goze batiyor hem sikistirmayi patlatiyor (olcum: kaydirmali klip 12.9 Mbps,
    sabit kamera 0.96 Mbps — ayni CRF'te 13 kat).
    """
    rng = rng or random.Random()
    pool = [
        v for v in search(query, api_key)
        if MIN_SEC <= int(v.get("duration", 0)) <= MAX_SEC and _best_file(v)
    ]
    if not pool:
        return []
    rng.shuffle(pool)
    out = []
    for video in pool[:count]:
        try:
            out.append(_download(video, query, work))
        except Exception:
            continue
    return out


def fetch_video(query: str, api_key: str, work: Path,
                rng: Optional[random.Random] = None) -> Optional[Dict[str, Any]]:
    """Tek klip indir (geriye donuk uyumluluk)."""
    hits = fetch_candidates(query, api_key, work, rng, count=1)
    return hits[0] if hits else None
