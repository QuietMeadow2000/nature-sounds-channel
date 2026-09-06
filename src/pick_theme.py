"""Tema secimi: agirlikli rastgele + sezonluk takvim + son N tekrar engeli.

Bolum 5 (rastgele secim kurali), 16.2 (agirliklar), 16.6 (sezonluk icerik).
"""
from __future__ import annotations

import random
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from util import REPO, STATE, PipelineError, history, load_json, load_yaml, log


def _in_season(today: date, start: str, end: str) -> bool:
    """MM-DD araligi; yil asan araliklari (12-01 -> 01-15) da kapsar."""
    sm, sd = (int(x) for x in start.split("-"))
    em, ed = (int(x) for x in end.split("-"))
    cur = (today.month, today.day)
    lo, hi = (sm, sd), (em, ed)
    if lo <= hi:
        return lo <= cur <= hi
    return cur >= lo or cur <= hi          # yil sonunu asan aralik


def active_season(today: date, seasonal: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    for season in seasonal.get("seasons", []):
        if _in_season(today, season["start"], season["end"]):
            return season
    return None


def recent_themes(n: int) -> List[str]:
    items = history()
    return [e["theme"] for e in items[-n:] if "theme" in e]


def effective_weights(cfg: Dict[str, Any]) -> Dict[str, float]:
    """weights.json + tavan/taban siniri; config'de olmayan temalar atilir."""
    themes = list(cfg["themes"].keys())
    raw = load_json(STATE / "weights.json", {}).get("weights") or {}
    sel = cfg.get("selection", {})
    floor = float(sel.get("weight_floor", 0.05))
    ceiling = float(sel.get("weight_ceiling", 0.35))

    weights = {t: float(raw.get(t, 1.0 / len(themes))) for t in themes}
    weights = {t: min(max(w, floor), ceiling) for t, w in weights.items()}
    total = sum(weights.values())
    if total <= 0:
        raise PipelineError("Tema agirliklarinin toplami sifir — weights.json bozuk.")
    return {t: w / total for t, w in weights.items()}


def pick(
    cfg: Dict[str, Any],
    today: Optional[date] = None,
    seed: Optional[int] = None,
) -> Tuple[str, Dict[str, Any]]:
    """(tema_adi, secim_bilgisi) dondur. seed verilirse secim tekrar uretilebilir."""
    today = today or date.today()
    rng = random.Random(seed)

    seasonal = load_yaml(REPO / "config" / "seasonal.yaml")
    season = active_season(today, seasonal)
    avoid_n = int(cfg.get("selection", {}).get("avoid_last_n", 2))
    recent = recent_themes(avoid_n)

    forced_by_season = bool(
        season and today.weekday() in season.get("weekdays", [])
    )

    if forced_by_season:
        pool = [t for t in season["themes"] if t in cfg["themes"]]
        candidates = [t for t in pool if t not in recent] or pool
        if not candidates:
            raise PipelineError(
                f"Sezon '{season['name']}' temalari config'de yok: {season['themes']}"
            )
        weights = effective_weights(cfg)
        chosen = rng.choices(candidates, weights=[weights[t] for t in candidates], k=1)[0]
        reason = f"sezonluk ({season['name']})"
    else:
        weights = effective_weights(cfg)
        candidates = [t for t in weights if t not in recent]
        if not candidates:                       # tum temalar son N icinde (cok az tema)
            candidates = list(weights)
        chosen = rng.choices(candidates, weights=[weights[t] for t in candidates], k=1)[0]
        reason = "agirlikli rastgele"

    info = {
        "theme": chosen,
        "reason": reason,
        "season": season["name"] if season else None,
        "title_hint": season.get("title_hint") if forced_by_season else None,
        "avoided": recent,
        "weight": round(effective_weights(cfg)[chosen], 4),
    }
    log.info("Tema: %s  (%s, kacinilan: %s)", chosen, reason, recent or "-")
    return chosen, info


if __name__ == "__main__":                       # elle deneme: python src/pick_theme.py
    import sys
    from util import setup_logging
    setup_logging()
    conf = load_yaml(REPO / "config" / (sys.argv[1] if len(sys.argv) > 1 else "channel_main.yaml"))
    for _ in range(10):
        print(pick(conf)[1])
