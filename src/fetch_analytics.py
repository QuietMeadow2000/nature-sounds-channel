"""Haftalik performans geri beslemesi (Bolum 16.2).

Pazartesileri calisir: son 28 gunde tema basina ortalama izlenme suresi ve izlenme
sayisini ceker, tema agirliklarini gunceller. Ilk 4 hafta veri az oldugundan
agirliklar pratikte esit kalir.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent))

import upload_youtube
from util import (
    REPO, STATE, PipelineError, history, load_json, load_yaml, log, save_json,
    setup_logging,
)

MIN_VIDEOS = 3            # bir temanin agirligi degismeden once gereken video sayisi
LOOKBACK_DAYS = 28


def video_stats(analytics, video_ids: List[str], start: date, end: date) -> Dict[str, Dict]:
    """video_id -> {views, avg_view_duration}."""
    out: Dict[str, Dict] = {}
    for i in range(0, len(video_ids), 200):          # API filtre uzunlugu siniri
        batch = video_ids[i:i + 200]
        resp = analytics.reports().query(
            ids="channel==MINE",
            startDate=start.isoformat(), endDate=end.isoformat(),
            metrics="views,averageViewDuration",
            dimensions="video",
            filters="video==" + ",".join(batch),
            maxResults=200,
        ).execute()
        for row in resp.get("rows", []):
            out[row[0]] = {"views": int(row[1]), "avg_view_duration": int(row[2])}
    return out


def compute_weights(cfg: Dict[str, Any], stats: Dict[str, Dict]) -> Dict[str, float]:
    """Temanin skoru = ortalama izlenme suresi x izlenme sayisi (izlenen saat vekili)."""
    sel = cfg.get("selection", {})
    floor = float(sel.get("weight_floor", 0.05))
    ceiling = float(sel.get("weight_ceiling", 0.35))
    themes = list(cfg["themes"].keys())

    totals: Dict[str, List[float]] = {t: [] for t in themes}
    for entry in history():
        vid = entry.get("video_id")
        theme = entry.get("theme")
        if vid and theme in totals and vid in stats:
            s = stats[vid]
            totals[theme].append(s["views"] * s["avg_view_duration"] / 3600.0)

    measured = {t: v for t, v in totals.items() if len(v) >= MIN_VIDEOS}
    if not measured:
        log.info("Yeterli veri yok (tema basina en az %d video) — agirliklar esit birakildi.",
                 MIN_VIDEOS)
        return {t: 1.0 / len(themes) for t in themes}

    scores = {t: sum(v) / len(v) for t, v in measured.items()}
    average = sum(scores.values()) / len(scores)
    raw = {t: scores.get(t, average) for t in themes}     # olculmemis tema = ortalama

    total = sum(raw.values()) or 1.0
    weights = {t: min(max(v / total, floor), ceiling) for t, v in raw.items()}
    norm = sum(weights.values())
    return {t: round(w / norm, 4) for t, w in weights.items()}


def summarize_errors() -> str:
    path = STATE / "errors.log"
    if not path.exists():
        return "hata yok"
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    recent = [l for l in lines if l[:10] >= (date.today() - timedelta(days=7)).isoformat()]
    return f"son 7 gunde {len(recent)} hata" if recent else "son 7 gunde hata yok"


def main() -> int:
    parser = argparse.ArgumentParser(description="Haftalik analytics -> tema agirliklari")
    parser.add_argument("--channel", default="config/channel_main.yaml")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    setup_logging()

    import os
    cfg = load_yaml(REPO / args.channel)
    secrets = {k: os.environ.get(k, "") for k in
               ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN")}

    ids = [e["video_id"] for e in history() if e.get("video_id")]
    if not ids:
        log.info("Henuz yuklenmis video yok — cikiliyor.")
        return 0

    analytics = upload_youtube.client(
        secrets["YT_CLIENT_ID"], secrets["YT_CLIENT_SECRET"], secrets["YT_REFRESH_TOKEN"],
        service="youtubeAnalytics",
    )
    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=LOOKBACK_DAYS)
    stats = video_stats(analytics, ids, start, end)
    log.info("Analytics: %d video icin veri geldi (%s - %s)", len(stats), start, end)

    weights = compute_weights(cfg, stats)
    for theme, w in sorted(weights.items(), key=lambda kv: -kv[1]):
        log.info("  %-16s %.3f", theme, w)
    log.info("Hata ozeti: %s", summarize_errors())

    if args.dry_run:
        log.info("DRY RUN — weights.json yazilmadi.")
        return 0

    save_json(STATE / "weights.json", {
        "updated": date.today().isoformat(),
        "window_days": LOOKBACK_DAYS,
        "videos_measured": len(stats),
        "weights": weights,
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
