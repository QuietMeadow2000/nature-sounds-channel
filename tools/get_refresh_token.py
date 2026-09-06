"""Tek seferlik: YouTube refresh token al (Bolum 3.3/5, yol haritasi adim 7).

Kullanim (kendi bilgisayarinda, bir kez):
    pip install google-auth-oauthlib
    python tools/get_refresh_token.py ~/Downloads/client_secret.json

Tarayici acilir, proje Gmail hesabiyla izin verirsin, terminale token dusen.
Cikan uc degeri GitHub Secrets'a gir: YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN.

UYARI (Bolum 16.7): OAuth consent screen "Testing" modundayken refresh token 7 gunde
bir gecersiz olur. Google Cloud Console'da "PUBLISH APP" ile "In production" moduna al.
"""
import json
import sys
from pathlib import Path

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 1
    secret_file = Path(sys.argv[1]).expanduser()
    if not secret_file.exists():
        print(f"Dosya yok: {secret_file}")
        return 1

    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_secrets_file(str(secret_file), SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")

    if not creds.refresh_token:
        print("\nRefresh token gelmedi. Google hesabinda bu uygulamanin erisimini kaldirip\n"
              "(myaccount.google.com/permissions) tekrar calistir.")
        return 1

    data = json.loads(secret_file.read_text())
    info = data.get("installed") or data.get("web") or {}
    print("\n" + "=" * 62)
    print("GitHub Secrets'a girilecek degerler:\n")
    print(f"YT_CLIENT_ID      = {info.get('client_id', creds.client_id)}")
    print(f"YT_CLIENT_SECRET  = {info.get('client_secret', creds.client_secret)}")
    print(f"YT_REFRESH_TOKEN  = {creds.refresh_token}")
    print("=" * 62)
    print("\nBu ciktiyi kimseyle paylasma; client_secret.json dosyasini repo'ya EKLEME.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
