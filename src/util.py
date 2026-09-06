"""Ortak yardimcilar: log, ffmpeg cagrilari, config yukleme, state dosyalari."""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO = Path(__file__).resolve().parent.parent
STATE = REPO / "state"
WORK = REPO / "work"
OUT = REPO / "out"   # manuel yayin paketleri

log = logging.getLogger("qm")


def setup_logging(verbose: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s  %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )


class PipelineError(RuntimeError):
    """Pipeline'i durduran, e-posta ile bildirilmesi gereken hata."""


# ---------------------------------------------------------------- ffmpeg

def _tool(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise PipelineError(
            f"{name} bulunamadi. Yerelde: brew install ffmpeg. "
            f"Runner'da: sudo apt-get install -y ffmpeg"
        )
    return path


def run(cmd: List[str], desc: str = "") -> str:
    """Komutu calistir, cikti dondur. Hata halinde stderr'i logla ve yukselt."""
    log.debug("$ %s", " ".join(cmd))
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        tail = "\n".join(proc.stderr.strip().splitlines()[-25:])
        raise PipelineError(f"{desc or cmd[0]} basarisiz (kod {proc.returncode}):\n{tail}")
    return proc.stdout


def ffmpeg(args: List[str], desc: str = "ffmpeg") -> None:
    run([_tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y"] + args, desc)


def ffprobe_json(path: Path, streams: str = "a") -> Dict[str, Any]:
    out = run(
        [
            _tool("ffprobe"), "-v", "error", "-print_format", "json",
            "-show_format", "-show_streams", "-select_streams", streams, str(path),
        ],
        f"ffprobe {path.name}",
    )
    return json.loads(out)


def duration_sec(path: Path, streams: str = "a") -> float:
    """Dosyanin saniye cinsinden suresi. Once stream, sonra container suresi."""
    info = ffprobe_json(path, streams)
    for st in info.get("streams", []):
        if st.get("duration"):
            return float(st["duration"])
    fmt_dur = info.get("format", {}).get("duration")
    if fmt_dur:
        return float(fmt_dur)
    raise PipelineError(f"{path.name}: sure okunamadi (bozuk dosya?)")


# ---------------------------------------------------------------- config / state

def load_yaml(path: Path) -> Dict[str, Any]:
    import yaml
    if not path.exists():
        raise PipelineError(f"Ayar dosyasi yok: {path}")
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        with path.open(encoding="utf-8") as fh:
            return json.load(fh)
    except json.JSONDecodeError as exc:
        raise PipelineError(f"{path} bozuk JSON: {exc}") from exc


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    tmp.replace(path)


def history() -> List[Dict[str, Any]]:
    return load_json(STATE / "history.json", [])


def append_history(entry: Dict[str, Any]) -> None:
    items = history()
    items.append(entry)
    save_json(STATE / "history.json", items)


def log_error(message: str) -> None:
    """Bolum 16.8 — haftalik analytics adimi bu dosyayi ozetler."""
    STATE.mkdir(parents=True, exist_ok=True)
    from datetime import datetime, timezone
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    with (STATE / "errors.log").open("a", encoding="utf-8") as fh:
        fh.write(f"{stamp}  {message}\n")


def paused() -> bool:
    """Bolum 16.7 — state/PAUSE varsa pipeline calismaz."""
    return (STATE / "PAUSE").exists()


# ---------------------------------------------------------------- dosya eslestirme

def normalize_token(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def match_files(folder: Path, token: str, exts=(".wav", ".flac", ".mp3", ".m4a", ".aif", ".aiff")) -> List[Path]:
    """Dosya adinda `token` gecen ses dosyalari.

    Konvansiyon: audio/<tema>/<match>__<kaynak-id>.flac
    Ornek: distant_thunder__freesound_512345.flac  ->  match "distant_thunder"
    """
    if not folder.is_dir():
        return []
    want = normalize_token(token)
    hits = [
        p for p in sorted(folder.iterdir())
        if p.suffix.lower() in exts and want in normalize_token(p.stem)
    ]
    return hits


def workdir(name: str) -> Path:
    d = WORK / name
    d.mkdir(parents=True, exist_ok=True)
    return d


def clean_work() -> None:
    if WORK.exists():
        shutil.rmtree(WORK)
