"""Yerel assets/ icerigini Google Drive'a yukler.

NEDEN AYRI BIR ARAC: pipeline Drive'i service account ile OKUYOR, ama service
account'larin depolama kotasi yok — kisisel bir Drive'a YAZAMIYORLAR (Google'in
kalici kisiti; Shared Drive ya da Workspace delegasyonu gerekiyor). Bu yuzden
yukleme, kullanicinin kendi OAuth yetkisiyle yapiliyor.

GUVENLIK: bu token GitHub secret'larina GIRMEZ. Yalnizca bu makinede,
~/.quiet-meadow-drive.json icinde durur (chmod 600). Pipeline'in token'i
Drive'a yazma yetkisi kazanmaz.

    python tools/drive_push.py            # yeni/degismis dosyalari yukle
    python tools/drive_push.py --dry-run  # ne yapacagini goster
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

TOKEN = Path.home() / ".quiet-meadow-drive.json"
SCOPES = ["https://www.googleapis.com/auth/drive"]
FOLDER_MIME = "application/vnd.google-apps.folder"


def client_config() -> dict:
    hits = sorted(Path.home().joinpath("Downloads").glob("client_secret*.json"),
                  key=lambda p: p.stat().st_mtime, reverse=True)
    if not hits:
        raise SystemExit(
            "client_secret*.json bulunamadi (~/Downloads).\n"
            "Google Cloud Console > Auth Platform > Clients > istemciye tikla > JSON indir."
        )
    return json.loads(hits[0].read_text())


def creds():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    if TOKEN.exists():
        c = Credentials.from_authorized_user_file(str(TOKEN), SCOPES)
        if c and c.valid:
            return c
        if c and c.expired and c.refresh_token:
            c.refresh(Request())
            TOKEN.write_text(c.to_json()); TOKEN.chmod(0o600)
            return c

    print("Drive yetkisi icin tarayici acilacak — quietmeadow2000@gmail.com ile onayla.")
    print("'Google hasn't verified this app' -> Advanced -> Go to ... (unsafe)\n")
    flow = InstalledAppFlow.from_client_config(client_config(), SCOPES)
    c = flow.run_local_server(port=0, prompt="consent", access_type="offline")
    TOKEN.write_text(c.to_json()); TOKEN.chmod(0o600)
    print(f"Token kaydedildi: {TOKEN} (yalnizca bu makinede, 600)")
    return c


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--root", default="nature-sounds-assets")
    args = ap.parse_args()

    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    svc = build("drive", "v3", credentials=creds(), cache_discovery=False)

    def children(pid):
        out, tok = [], None
        while True:
            r = svc.files().list(q=f"'{pid}' in parents and trashed=false",
                                 fields="nextPageToken, files(id,name,mimeType,size)",
                                 pageSize=200, pageToken=tok).execute()
            out += r.get("files", []); tok = r.get("nextPageToken")
            if not tok:
                return out

    def find(pid, name):
        return next((c for c in children(pid) if c["name"] == name), None)

    def ensure(pid, name):
        hit = find(pid, name)
        if hit and hit["mimeType"] == FOLDER_MIME:
            return hit["id"]
        if args.dry_run:
            print(f"    [klasor olusturulacak] {name}")
            return None
        return svc.files().create(
            body={"name": name, "mimeType": FOLDER_MIME, "parents": [pid]},
            fields="id").execute()["id"]

    r = svc.files().list(q=f"name='{args.root}' and mimeType='{FOLDER_MIME}' and trashed=false",
                         fields="files(id,name)").execute().get("files", [])
    if not r:
        raise SystemExit(f"Drive'da '{args.root}' klasoru yok.")
    root = r[0]["id"]

    assets = REPO / "assets"
    plan = []
    for sub in ("audio", "clips", "photos"):
        d = assets / sub
        if not d.is_dir():
            continue
        for theme in sorted(p for p in d.iterdir() if p.is_dir()):
            files = [f for f in sorted(theme.iterdir())
                     if f.is_file() and not f.name.startswith(".")]
            if files:
                plan.append(([sub, theme.name], files))
    if (assets / "fonts").is_dir():
        fs = [f for f in sorted((assets / "fonts").iterdir())
              if f.is_file() and not f.name.startswith(".")]
        if fs:
            plan.append((["fonts"], fs))
    if (assets / "logo.png").exists():
        plan.append(([], [assets / "logo.png"]))

    yuklendi = atlandi = 0
    for parts, files in plan:
        print(f"  {'/'.join(parts) or '(kok)'}/")
        pid = root
        for part in parts:
            pid = ensure(pid, part)
            if pid is None:
                break
        if pid is None:
            continue
        mevcut = {c["name"]: c for c in children(pid)}
        for f in files:
            hit = mevcut.get(f.name)
            if hit and int(hit.get("size", 0)) == f.stat().st_size:
                print(f"    {f.name:<46} zaten var, atlandi")
                atlandi += 1
                continue
            if args.dry_run:
                print(f"    {f.name:<46} [yuklenecek {f.stat().st_size/1e6:.0f} MB]")
                continue
            media = MediaFileUpload(str(f), resumable=f.stat().st_size > 5_000_000)
            if hit:
                svc.files().update(fileId=hit["id"], media_body=media).execute()
                print(f"    {f.name:<46} guncellendi")
            else:
                svc.files().create(body={"name": f.name, "parents": [pid]},
                                   media_body=media, fields="id").execute()
                print(f"    {f.name:<46} {f.stat().st_size/1e6:6.0f} MB")
            yuklendi += 1
    print(f"\n  {yuklendi} yuklendi, {atlandi} atlandi")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
