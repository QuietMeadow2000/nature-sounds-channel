"""Tek seferlik: YouTube refresh token al (Bolum 3.3/5, yol haritasi adim 7).

Kullanim (kendi bilgisayarinda, bir kez):
    pip install google-auth-oauthlib
    python tools/get_refresh_token.py            # ~/Downloads'tan kendi bulur
    python tools/get_refresh_token.py <yol>    # ya da acikca belirt

Tarayici acilir, proje Gmail hesabiyla izin verirsin, terminale token dusen.
Cikan uc degeri GitHub Secrets'a gir: YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN.

UYARI (Bolum 16.7): OAuth consent screen "Testing" modundayken refresh token 7 gunde
bir gecersiz olur. Google Cloud Console'da "PUBLISH APP" ile "In production" moduna al.
"""
import json
import sys
from pathlib import Path
from typing import Optional

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]


def from_prompt() -> dict:
    """JSON yoksa degerleri elle al.

    Google (2026) mevcut client secret'i artik goster/indir etmiyor; JSON indirme
    yolu yalnizca istemci ILK olusturuldugunda calisiyor. Bu yuzden degerleri
    dogrudan alabiliyoruz. Secret getpass ile aliniyor — ekrana yazilmaz,
    kabuk gecmisine dusmez.
    """
    import getpass
    print("client_secret JSON bulunamadi — degerleri elle girebilirsin.")
    print("Google Cloud Console > Auth Platform > Clients > istemciye tikla\n")
    client_id = input("Client ID    : ").strip()
    if not client_id:
        raise SystemExit("Client ID bos birakilamaz.")
    client_secret = getpass.getpass("Client secret: ").strip()
    if not client_secret:
        raise SystemExit("Client secret bos birakilamaz.\n"
                         "Secret'i goremiyorsan detay sayfasindaki 'Client secrets' "
                         "bolumunden yeni bir tane olustur; bir kez gosterilir.")
    return {"installed": {
        "client_id": client_id,
        "client_secret": client_secret,
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": TOKEN_URI,
        "redirect_uris": ["http://localhost"],
    }}


def find_secret() -> Optional[Path]:
    """Argüman verilmediyse ~/Downloads icindeki en yeni client_secret'i bul."""
    hits = sorted(
        Path.home().joinpath("Downloads").glob("client_secret*.json"),
        key=lambda p: p.stat().st_mtime, reverse=True,
    )
    return hits[0] if hits else None


def main() -> int:
    if len(sys.argv) > 2:
        print(__doc__)
        return 1
    secret_file = Path(sys.argv[1]).expanduser() if len(sys.argv) == 2 else find_secret()

    from google_auth_oauthlib.flow import InstalledAppFlow

    if secret_file and secret_file.exists():
        print(f"Kullanilan istemci dosyasi: {secret_file.name}")
        config = json.loads(secret_file.read_text())
    else:
        config = from_prompt()

    flow = InstalledAppFlow.from_client_config(config, SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")

    if not creds.refresh_token:
        print("\nRefresh token gelmedi. Google hesabinda bu uygulamanin erisimini kaldirip\n"
              "(myaccount.google.com/permissions) tekrar calistir.")
        return 1

    info = config.get("installed") or config.get("web") or {}
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
