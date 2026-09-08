"""Kimlik bilgisi saglik kontrolu — hicbir sirri yazdirmadan.

GitHub secret'lari geri okunamaz; bu script onlari gercek ortamda sinar ve
token'in hangi kanala bagli oldugunu soyler. Yalnizca okuma yapar.

    python tools/check_auth.py
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def main() -> int:
    missing = [k for k in ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN")
               if not os.environ.get(k)]
    if missing:
        print("EKSIK secret:", ", ".join(missing))
        return 1

    import upload_youtube as yt
    try:
        svc = yt.client(os.environ["YT_CLIENT_ID"], os.environ["YT_CLIENT_SECRET"],
                        os.environ["YT_REFRESH_TOKEN"])
        r = svc.channels().list(part="snippet,statistics", mine=True).execute()
    except Exception as exc:
        print("KIMLIK DOGRULAMA BASARISIZ")
        print(f"  {type(exc).__name__}: {str(exc)[:200]}")
        print("\n  invalid_grant goruyorsan token gecersiz olmus:")
        print("  myaccount.google.com/permissions -> erisimi kaldir -> token'i yenile")
        return 1

    items = r.get("items", [])
    if not items:
        print("Token gecerli ama hicbir kanal donmedi — yanlis hesapla yetkilendirilmis olabilir.")
        return 1

    ch = items[0]
    s, st = ch["snippet"], ch.get("statistics", {})
    print("KIMLIK DOGRULANDI")
    print(f"  kanal    : {s['title']}")
    print(f"  handle   : {s.get('customUrl', '-')}")
    print(f"  kanal id : {ch['id']}")
    print(f"  video    : {st.get('videoCount')}   abone: {st.get('subscriberCount')}")

    # Son yuklemeler — kanaldaki videolarin gercek durumu
    ch = svc.channels().list(part="contentDetails", mine=True).execute()
    up = ch["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
    items = svc.playlistItems().list(part="snippet,status", playlistId=up,
                                     maxResults=25).execute().get("items", [])
    print(f"\n  yuklemeler ({len(items)}):")
    vids = [i["snippet"]["resourceId"]["videoId"] for i in items]
    durum = {}
    if vids:
        r = svc.videos().list(part="status,snippet", id=",".join(vids)).execute()
        durum = {v["id"]: v for v in r.get("items", [])}
    for i in items:
        vid = i["snippet"]["resourceId"]["videoId"]
        v = durum.get(vid, {})
        st = v.get("status", {})
        print(f"    {vid}  {st.get('privacyStatus','?'):<9} "
              f"{st.get('uploadStatus','?'):<10} {i['snippet']['title'][:44]}")

    pl = svc.playlists().list(part="snippet,contentDetails", mine=True,
                              maxResults=25).execute()
    plist = pl.get("items", [])
    print(f"\n  playlist ({len(plist)}):")
    for p in plist:
        n = p.get("contentDetails", {}).get("itemCount", "?")
        print(f"    {p['id']}  {p['snippet']['title']:<22} ({n} video)")
    if not plist:
        print("    (yok — config'deki playlist_id alanlari bos kalabilir)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
