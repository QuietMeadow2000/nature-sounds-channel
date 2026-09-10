"""Yayin hizi korumalari — 9 Eylul 2026 askiya alinmasindan sonra eklendi.

NE OLDU: hesap 6 Eylul'de acildi, 7 Eylul'de API yetkisi aldi, 7 ve 8 Eylul
gecelerinde saniyesi sabit bir cron'dan otomatik video yukledi. 9 Eylul'de
Google hesabi "bot tarafindan olusturulmus olabilir" gerekcesiyle askiya aldi.
Itiraz kabul edildi, ama desen tekrarlanirsa ikinci askiya alma kalici olabilir.

Bu modul o deseni kodla imkansiz kiliyor. Niyet beyani yeterli degil.
"""
from __future__ import annotations

import random
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

from util import history, log


def uploads_in_last_days(gun: int, channel_key: str) -> int:
    """Son `gun` gunde API ile yuklenen video sayisi (elle yayinlananlar sayilmaz)."""
    sinir = date.today() - timedelta(days=gun)
    n = 0
    for e in history():
        if e.get("channel") != channel_key or not e.get("video_id"):
            continue
        try:
            if date.fromisoformat(e["date"]) > sinir:
                n += 1
        except (ValueError, KeyError):
            continue
    return n


def channel_age_days(svc) -> Optional[int]:
    """Kanalin kac gunluk oldugu. Okunamazsa None."""
    try:
        r = svc.channels().list(part="snippet", mine=True).execute()
        kurulus = r["items"][0]["snippet"]["publishedAt"]
        d = datetime.fromisoformat(kurulus.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - d).days
    except Exception as exc:
        log.warning("Kanal yasi okunamadi (%s) — yas kontrolu atlaniyor.",
                    type(exc).__name__)
        return None


def may_publish(cfg: Dict[str, Any], svc=None) -> Tuple[bool, str]:
    """API ile yayinlanabilir mi? (izin, gerekce) dondurur.

    Reddederse cagiran manuel moda duser — video yine uretilir, sadece
    otomatik yuklenmez.
    """
    p = cfg.get("publish_guard") or {}
    key = cfg["channel"]["key"]

    min_yas = int(p.get("min_channel_age_days", 0) or 0)
    if min_yas and svc is not None:
        yas = channel_age_days(svc)
        if yas is not None and yas < min_yas:
            return False, (f"kanal {yas} gunluk, otomatik yayin icin en az {min_yas} gun "
                           f"gerekiyor (yeni kanaldan gunluk API yuklemesi bot sinyali)")

    hafta = int(p.get("max_per_week", 0) or 0)
    if hafta:
        n = uploads_in_last_days(7, key)
        if n >= hafta:
            return False, f"son 7 gunde {n} otomatik yukleme var, sinir {hafta}"

    gun_ara = int(p.get("min_days_between", 0) or 0)
    if gun_ara:
        n = uploads_in_last_days(gun_ara, key)
        if n:
            return False, f"son {gun_ara} gunde zaten yukleme yapilmis"

    return True, "uygun"


def publish_jitter(cfg: Dict[str, Any], rng: Optional[random.Random] = None) -> int:
    """Yuklemeden once beklenecek saniye.

    Cron her gece ayni saniyede tetikleniyor ve yukleme neredeyse sabit bir
    gecikmeyle oluyordu — makine deseni. Rastgele kayma bunu kiriyor.
    Kozmetik bir onlem ama bedava.
    """
    p = cfg.get("publish_guard") or {}
    en_fazla = int(p.get("jitter_minutes", 0) or 0)
    if en_fazla <= 0:
        return 0
    return int((rng or random.Random()).uniform(0, en_fazla) * 60)
