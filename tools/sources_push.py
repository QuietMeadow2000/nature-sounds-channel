"""state/sources.csv'yi Drive'a Google Sheet olarak yukler.

Defter repo'da tutuluyor (git gecmisi zaman damgali kanit saglar), Drive'daki
kopya pipeline'in okudugu yer. Drive API CSV'yi yuklerken Sheet'e cevirebiliyor,
bu yuzden Sheets API'ye gerek yok.

    python tools/sources_push.py
"""
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parent.parent
CSV = REPO / "state" / "sources.csv"
TOKEN = Path.home() / ".quiet-meadow-drive.json"
SCOPES = ["https://www.googleapis.com/auth/drive"]
SHEET = "application/vnd.google-apps.spreadsheet"
FOLDER = "application/vnd.google-apps.folder"


def main() -> int:
    if not CSV.exists():
        print(f"{CSV} yok"); return 1
    if not TOKEN.exists():
        print("Drive yetkisi yok — once: python tools/drive_push.py"); return 1

    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    svc = build("drive", "v3",
                credentials=Credentials.from_authorized_user_file(str(TOKEN), SCOPES),
                cache_discovery=False)
    r = svc.files().list(q=f"name='nature-sounds-assets' and mimeType='{FOLDER}' "
                           "and trashed=false", fields="files(id)").execute()
    if not r.get("files"):
        print("nature-sounds-assets klasoru bulunamadi"); return 1
    root = r["files"][0]["id"]

    mevcut = svc.files().list(q=f"'{root}' in parents and name='sources' and trashed=false",
                              fields="files(id,mimeType)").execute().get("files", [])
    media = MediaFileUpload(str(CSV), mimetype="text/csv", resumable=False)
    if mevcut:
        svc.files().update(fileId=mevcut[0]["id"], media_body=media).execute()
        print(f"guncellendi: sources ({mevcut[0]['id']})")
    else:
        f = svc.files().create(
            body={"name": "sources", "mimeType": SHEET, "parents": [root]},
            media_body=media, fields="id").execute()
        print(f"olusturuldu: sources ({f['id']})")

    n = sum(1 for _ in CSV.open()) - 1
    print(f"{n} kayit yuklendi")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
