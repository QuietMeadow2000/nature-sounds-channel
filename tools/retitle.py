"""Yayindaki videolarin baslik/aciklama/etiketlerini yeniden uretir.

Eski videolar jenerik kategori basligiyla yayinlandi ("Thunderstorm Rain Sounds")
ve 10M aboneli kanallarla yarisiyorlar. Kayitlarin gercek karakteri config'de
`character` alaninda; bu arac o bilgiyle metinleri yeniden uretip gunceller.

    python tools/retitle.py                # kuru calisma — sadece gosterir
    python tools/retitle.py --apply        # YouTube'da gunceller
    python tools/retitle.py --only <id>    # tek video
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from util import load_yaml, history, save_json, setup_logging, log, STATE  # noqa: E402
import gen_metadata  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="YouTube'da gercekten guncelle")
    ap.add_argument("--only", help="yalnizca bu video_id")
    ap.add_argument("--channel", default="config/channel_main.yaml")
    ap.add_argument("--sleep", type=float, default=65.0,
                    help="istekler arasi bekleme (Groq dakikalik token siniri)")
    args = ap.parse_args()
    setup_logging()

    cfg = load_yaml(REPO / args.channel)
    items = [e for e in history() if e.get("video_id")]
    if args.only:
        items = [e for e in items if e["video_id"] == args.only]
    if not items:
        print("Guncellenecek kayit yok."); return 1

    svc = None
    if args.apply:
        import upload_youtube as yt
        eksik = [k for k in ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN")
                 if not os.environ.get(k)]
        if eksik:
            print("EKSIK secret:", ", ".join(eksik)); return 1
        svc = yt.client(os.environ["YT_CLIENT_ID"], os.environ["YT_CLIENT_SECRET"],
                        os.environ["YT_REFRESH_TOKEN"])

    degisen = 0
    for i, e in enumerate(items):
        tema = e["theme"]
        if tema not in cfg["themes"]:
            print(f"  ! {e['video_id']}: '{tema}' config'de yok, atlandi"); continue

        # Videonun KENDI suresiyle uret — baslikta dogru sure yazsin.
        c = dict(cfg)
        c["audio"] = dict(cfg["audio"])
        c["audio"]["duration_min"] = round(e.get("audio", {}).get("duration_sec", 3600) / 60)

        meta = gen_metadata.generate(
            tema, c,
            e.get("audio", {"layers": []}),
            e.get("video", {"visual_kind": "clip"}),
            season_hint=e.get("season_hint"),
        )
        print(f"\n[{i+1}/{len(items)}] {e['video_id']}  ({tema}, {c['audio']['duration_min']} dk)")
        print(f"  eski : {e.get('title','-')}")
        print(f"  yeni : {meta['title']}")
        print(f"  etiket: {', '.join(meta['tags'][:6])} ...")

        if svc:
            body = {"id": e["video_id"], "snippet": {
                "title": meta["title"], "description": meta["description"],
                "tags": meta["tags"],
                "categoryId": str(cfg["channel"]["category_id"]),
                "defaultLanguage": cfg["channel"].get("default_language", "en"),
            }}
            svc.videos().update(part="snippet", body=body).execute()
            e["title"] = meta["title"]
            e["tags"] = meta["tags"]
            e["metadata_by"] = meta.get("generated_by")
            degisen += 1
            print("  -> guncellendi")

        if i < len(items) - 1:
            time.sleep(args.sleep)

    if svc and degisen:
        # history() kopya donduruyor olabilir; tum kaydi yeniden okuyup
        # guncellenen alanlari video_id uzerinden isliyoruz.
        tum = history()
        yeni = {e["video_id"]: e for e in items}
        for kayit in tum:
            g = yeni.get(kayit.get("video_id"))
            if g:
                kayit["title"] = g["title"]
                kayit["tags"] = g["tags"]
                kayit["metadata_by"] = g.get("metadata_by")
        save_json(STATE / "history.json", tum)
        print(f"\n{degisen} video guncellendi")
    elif not svc:
        print(f"\nKURU CALISMA — hicbir sey degismedi. Uygulamak icin: --apply")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
