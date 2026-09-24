"""config/channel_localtest.yaml'i channel_main.yaml'dan uretir.

Iki dosyayi elle guncellemek isliyor: bir seferinde localtest `enabled`
bayraklarini hic almadi ve sesi olmayan temalar orada acik gorundu.
Tek kaynak main; test dosyasi ondan turetiliyor.

    python tools/sync_localtest.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MAIN = REPO / "config" / "channel_main.yaml"
TEST = REPO / "config" / "channel_localtest.yaml"

# (aranan, yerine) — test dosyasinda farkli olmasi gereken tek sey bunlar
OVERRIDES = [
    ("  key: main", "  key: localtest"),
    ("  duration_min: 180", "  duration_min: 2   # YEREL TEST"),
]
HEADER = "# URETILMIS DOSYA — elle duzenleme. Kaynak: config/channel_main.yaml\n" \
         "# Yeniden uretmek icin: python tools/sync_localtest.py\n"


def main() -> int:
    text = MAIN.read_text(encoding="utf-8")
    for old, new in OVERRIDES:
        if text.count(old) != 1:
            print(f"HATA: {old!r} main'de {text.count(old)} kez geciyor, 1 bekleniyordu")
            return 1
        text = text.replace(old, new)
    TEST.write_text(HEADER + text, encoding="utf-8")
    print(f"{TEST.name} yeniden uretildi ({len(text.splitlines())} satir)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
