"""Google Drive asset deposu — salt okunur indirme + kaynak defteri kontrolu.

Bolum 3.8 / 16.1. Service account'a yalnizca Viewer yetkisi verilir; script hicbir
seyi Drive'a yazmaz. Pexels'ten otomatik inen kliplerin kaydi Drive'daki Sheet'e
degil, repo'daki state/sources_auto.jsonl dosyasina yazilir (asagida `note_auto_source`)
— her gun commit'lendigi icin git gecmisi zaman damgali kanit olur ve service
account'un yazma yetkisine ihtiyac kalmaz.
"""
from __future__ import annotations

import csv
import io
import json
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set

from util import STATE, PipelineError, log, save_json

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
FOLDER_MIME = "application/vnd.google-apps.folder"
SHEET_MIME = "application/vnd.google-apps.spreadsheet"


def _service(sa_json: str):
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    try:
        info = json.loads(sa_json)
    except json.JSONDecodeError as exc:
        raise PipelineError(f"GDRIVE_SA_JSON gecerli JSON degil: {exc}") from exc
    creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _children(svc, parent_id: str, mime: Optional[str] = None) -> List[Dict[str, Any]]:
    query = f"'{parent_id}' in parents and trashed = false"
    if mime:
        query += f" and mimeType = '{mime}'"
    items, token = [], None
    while True:
        resp = svc.files().list(
            q=query, fields="nextPageToken, files(id, name, mimeType, size)",
            pageSize=200, pageToken=token,
            supportsAllDrives=True, includeItemsFromAllDrives=True,
        ).execute()
        items += resp.get("files", [])
        token = resp.get("nextPageToken")
        if not token:
            return items


def _find(svc, parent_id: str, name: str) -> Optional[Dict[str, Any]]:
    for item in _children(svc, parent_id):
        if item["name"] == name:
            return item
    return None


def _root(svc, folder_name: str) -> str:
    resp = svc.files().list(
        q=f"name = '{folder_name}' and mimeType = '{FOLDER_MIME}' and trashed = false",
        fields="files(id, name)", pageSize=10,
        supportsAllDrives=True, includeItemsFromAllDrives=True,
    ).execute()
    files = resp.get("files", [])
    if not files:
        raise PipelineError(
            f"Drive'da '{folder_name}' klasoru gorunmuyor.\n"
            f"Klasoru service account'un e-postasiyla Viewer olarak paylastin mi? (Bolum 3.8/5)"
        )
    return files[0]["id"]


def _download(svc, file_id: str, dest: Path) -> None:
    from googleapiclient.http import MediaIoBaseDownload

    dest.parent.mkdir(parents=True, exist_ok=True)
    request = svc.files().get_media(fileId=file_id, supportsAllDrives=True)
    with dest.open("wb") as fh:
        downloader = MediaIoBaseDownload(fh, request, chunksize=8 * 1024 * 1024)
        done = False
        while not done:
            _, done = downloader.next_chunk()


def _pull_folder(svc, folder: Optional[Dict[str, Any]], dest: Path) -> int:
    if not folder:
        return 0
    count = 0
    for item in _children(svc, folder["id"]):
        if item["mimeType"] == FOLDER_MIME:
            continue
        _download(svc, item["id"], dest / item["name"])
        count += 1
    return count


def sync(theme: str, sa_json: str, root_name: str, dest: Path,
         sheet_name: str = "sources") -> Set[str]:
    """Bugun gereken varliklari indir. Kaynak defterindeki dosya adlarini dondur."""
    svc = _service(sa_json)
    root_id = _root(svc, root_name)
    log.info("Drive: '%s' klasoru bulundu", root_name)

    total = 0
    for kind in ("audio", "clips", "photos"):
        parent = _find(svc, root_id, kind)
        if not parent:
            continue
        theme_folder = _find(svc, parent["id"], theme)
        n = _pull_folder(svc, theme_folder, dest / kind / theme)
        log.info("  %-7s %s: %d dosya", kind, theme, n)
        total += n

    fonts = _find(svc, root_id, "fonts")
    total += _pull_folder(svc, fonts, dest / "fonts")

    logo = _find(svc, root_id, "logo.png")
    if logo:
        _download(svc, logo["id"], dest / "logo.png")
        total += 1
    log.info("Drive: toplam %d dosya indirildi", total)

    return read_registry(svc, root_id, sheet_name)


def read_registry(svc, root_id: str, sheet_name: str) -> Set[str]:
    """`sources` Sheet'ini CSV olarak disa aktarip kayitli dosya adlarini dondur.

    Sheets API'ye gerek yok — Drive `files.export` Google Sheet'i CSV verir.
    """
    sheet = _find(svc, root_id, sheet_name)
    if not sheet or sheet["mimeType"] != SHEET_MIME:
        log.warning("Kaynak defteri ('%s') bulunamadi — dosya kontrolu atlandi.", sheet_name)
        return set()

    data = svc.files().export(fileId=sheet["id"], mimeType="text/csv").execute()
    text = data.decode("utf-8") if isinstance(data, bytes) else str(data)
    names: Set[str] = set()
    for row in csv.reader(io.StringIO(text)):
        if row and row[0].strip():
            names.add(row[0].strip())
    log.info("Kaynak defteri: %d kayit", len(names))
    return names


def check_registered(used: Iterable[str], registry: Set[str]) -> None:
    """Bolum 16.1 — defterde olmayan dosya pipeline'a girmez."""
    if not registry:
        return
    missing = [name for name in used if name and not name.startswith("pexels:")
               and name not in registry]
    if missing:
        raise PipelineError(
            "Kaynak defterinde kayitli olmayan dosya kullanildi: "
            + ", ".join(missing)
            + "\nOnce `sources` Sheet'ine satir ekle (dosya, kaynak URL, lisans, yazar, tarih)."
        )


def note_auto_source(entry: Dict[str, Any]) -> None:
    """Otomatik inen (Pexels) varliklari repo icindeki deftere ekle."""
    STATE.mkdir(parents=True, exist_ok=True)
    with (STATE / "sources_auto.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
