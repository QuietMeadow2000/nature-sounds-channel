"""Ses pipeline'i: 3-5 dakikalik CC0 kayitlardan 60 dakikalik kesintisiz miks.

Bolum 6. Yontem:
  1) Her kaydi -18 LUFS'a getir (olc + sabit kazanc; dinamik islem YOK, ambient'te pompalar).
  2) Her kayittan "loop birimi" uret: son X saniyeyi basina acrossfade ile bindir.
     Boylece birim kendi icinde tiklamasiz dongu yapar.
  3) Her katmani KENDI periyoduyla, farkli offset'ten baslatarak 60 dk'ya uzat.
     Periyotlar farkli oldugu icin tekrarlar hizalanmaz -> kulak "dongu" duymaz.
  4) amix (normalize=0) + tek seferlik sabit kazanc duzeltmesi + fade in/out.
  5) AAC 192 kbps.

Ayrica ek noktasini iceren 30 sn'lik QC kesiti uretir (Bolum 6, kalite kontrolu).
"""
from __future__ import annotations

import json
import math
import random
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from util import (
    PipelineError, _tool, duration_sec, ffmpeg, log, match_files, run,
)

AFORMAT = "aformat=sample_fmts=fltp:sample_rates={sr}:channel_layouts=stereo"


# ---------------------------------------------------------------- olcum

def measure_lufs(path: Path, target: float) -> float:
    """Kaydin entegre yuksekligini (LUFS) dondur. loudnorm 1. gecis, JSON stderr'de."""
    cmd = [
        _tool("ffmpeg"), "-hide_banner", "-nostats", "-i", str(path),
        "-af", f"loudnorm=I={target}:TP=-1.5:LRA=11:print_format=json",
        "-f", "null", "-",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        tail = "\n".join(proc.stderr.strip().splitlines()[-15:])
        raise PipelineError(f"loudnorm olcumu basarisiz ({path.name}):\n{tail}")

    blocks = re.findall(r"\{[^{}]*\"input_i\"[^{}]*\}", proc.stderr, re.S)
    if not blocks:
        raise PipelineError(f"loudnorm JSON okunamadi: {path.name}")
    value = json.loads(blocks[-1])["input_i"]
    if value in ("-inf", "inf", "nan"):
        raise PipelineError(f"{path.name}: sessiz veya bozuk kayit (input_i={value})")
    return float(value)


# ---------------------------------------------------------------- adim 1-2

def normalize_source(src: Path, dst: Path, target_lufs: float, sample_rate: int) -> float:
    """Sabit kazancla hedef LUFS'a getir; 44.1k stereo float'a cevir. Uygulanan dB'yi dondur."""
    measured = measure_lufs(src, target_lufs)
    delta = target_lufs - measured
    ffmpeg(
        ["-i", str(src),
         "-af", f"volume={delta:.3f}dB," + AFORMAT.format(sr=sample_rate),
         "-c:a", "pcm_s24le", str(dst)],
        f"normalize {src.name}",
    )
    log.info("  %-42s %6.1f LUFS  ->  %+.1f dB", src.name, measured, delta)
    return delta


def make_loop_unit(src: Path, dst: Path, crossfade: float) -> float:
    """Son `crossfade` sn'yi basa bindirerek dongu birimi uret. Birim suresini dondur."""
    dur = duration_sec(src)
    if dur < crossfade * 4:
        raise PipelineError(
            f"{src.name}: {dur:.0f} sn cok kisa (crossfade {crossfade:.0f} sn icin "
            f"en az {crossfade * 4:.0f} sn gerekir). Daha uzun bir kayit sec."
        )
    head_end = dur - crossfade
    chain = (
        f"[0:a]asplit=2[a][b];"
        f"[a]atrim=0:{head_end:.6f},asetpts=PTS-STARTPTS[a1];"
        f"[b]atrim={head_end:.6f}:{dur:.6f},asetpts=PTS-STARTPTS[b1];"
        f"[b1][a1]acrossfade=d={crossfade:.6f}:c1=tri:c2=tri[out]"
    )
    ffmpeg(
        ["-i", str(src), "-filter_complex", chain, "-map", "[out]",
         "-c:a", "pcm_s24le", str(dst)],
        f"loop unit {src.name}",
    )
    unit_len = duration_sec(dst)
    log.info("  %-42s %6.0f sn  ->  birim %.0f sn", src.name, dur, unit_len)
    return unit_len


# ---------------------------------------------------------------- adim 3-4

def _mix_filter(
    layers: List[Dict[str, Any]], total_sec: float, sample_rate: int,
    gain_db: float = 0.0, fade_in: float = 0.0, fade_out: float = 0.0,
) -> str:
    parts = []
    for i, layer in enumerate(layers):
        start = layer["offset"]
        parts.append(
            f"[{i}:a]atrim=start={start:.6f}:end={start + total_sec:.6f},"
            f"asetpts=PTS-STARTPTS,volume={layer['gain']:.4f},"
            + AFORMAT.format(sr=sample_rate) + f"[a{i}]"
        )
    ins = "".join(f"[a{i}]" for i in range(len(layers)))
    # normalize=0 sart: varsayilan amix girdi sayisina boler, seviyeyi oldurur.
    parts.append(f"{ins}amix=inputs={len(layers)}:duration=first:normalize=0[m]")

    tail = "[m]"
    post = []
    if abs(gain_db) > 0.01:
        post.append(f"volume={gain_db:.3f}dB")
    if fade_in > 0:
        post.append(f"afade=t=in:st=0:d={fade_in:.3f}")
    if fade_out > 0:
        post.append(f"afade=t=out:st={total_sec - fade_out:.3f}:d={fade_out:.3f}")
    if post:
        parts.append(tail + ",".join(post) + "[out]")
        return ";".join(parts)
    parts[-1] = parts[-1].replace("[m]", "[out]")
    return ";".join(parts)


def _loop_inputs(layers: List[Dict[str, Any]], total_sec: float) -> List[str]:
    args: List[str] = []
    for layer in layers:
        needed = total_sec + layer["offset"]
        extra = max(0, math.ceil(needed / layer["unit_len"]) - 1)
        args += ["-stream_loop", str(extra), "-i", str(layer["unit"])]
    return args


def render_mix(
    layers: List[Dict[str, Any]], out: Path, total_sec: float, sample_rate: int,
    gain_db: float, fade_in: float, fade_out: float, bitrate: str,
) -> None:
    args = _loop_inputs(layers, total_sec)
    args += [
        "-filter_complex", _mix_filter(layers, total_sec, sample_rate, gain_db, fade_in, fade_out),
        "-map", "[out]", "-ar", str(sample_rate), "-ac", "2",
    ]
    if out.suffix.lower() in (".wav",):
        args += ["-c:a", "pcm_s16le"]
    else:
        args += ["-c:a", "aac", "-b:a", bitrate]
    args.append(str(out))
    ffmpeg(args, "miks render")


# ---------------------------------------------------------------- QC kesiti

def seam_clip(audio: Path, out: Path, unit_len: float, window: float = 30.0) -> Optional[float]:
    """Ana katmanin ilk ek noktasini ortalayan kisa kesit (kulakla kontrol icin)."""
    seam = unit_len
    while seam < 60:                       # cok basta olmasin, fade-in'e denk gelmesin
        seam += unit_len
    if seam + window / 2 > duration_sec(audio):
        return None
    ffmpeg(
        ["-ss", f"{seam - window / 2:.3f}", "-i", str(audio), "-t", f"{window:.3f}",
         "-c:a", "pcm_s16le", str(out)],
        "QC kesiti",
    )
    return seam


# ---------------------------------------------------------------- ana giris

def build(
    theme: str, cfg: Dict[str, Any], assets: Path, work: Path, seed: int,
) -> Dict[str, Any]:
    """Temanin 60 dakikalik sesini uret. history.json'a yazilacak tarifi dondur."""
    acfg = cfg["audio"]
    rng = random.Random(seed)
    total = float(acfg["duration_min"]) * 60.0
    sr = int(acfg["sample_rate"])
    xfade = float(acfg["crossfade_sec"])
    jitter = float(acfg.get("gain_jitter", 0.10))

    folder = assets / "audio" / theme
    spec = cfg["themes"][theme]["mix"]

    log.info("Ses: %s  (%s)", theme, folder)
    layers: List[Dict[str, Any]] = []
    for idx, item in enumerate(spec):
        hits = match_files(folder, item["match"])
        if not hits:
            if item["role"] == "main":
                raise PipelineError(
                    f"'{theme}' ana katmani icin dosya yok: {folder}/*{item['match']}*.\n"
                    f"Konvansiyon: <match>__<kaynak>.flac  (Bolum 3.5)"
                )
            log.warning("  katman atlandi (dosya yok): %s", item["match"])
            continue

        src = rng.choice(hits)
        norm = work / f"norm_{idx}.wav"
        unit = work / f"unit_{idx}.wav"
        applied = normalize_source(src, norm, float(acfg["target_lufs"]), sr)
        unit_len = make_loop_unit(norm, unit, xfade)

        # Bolum 5: oranlar her gun +-%10 oynar -> her video olculebilir sekilde farkli.
        gain = float(item["gain"]) * (1.0 + rng.uniform(-jitter, jitter))
        # Ana katman 0'dan baslar; digerleri kendi periyodunun ortasindan -> tekrarlar hizalanmaz.
        offset = 0.0 if idx == 0 else round(rng.uniform(0.17, 0.83) * unit_len, 3)

        layers.append({
            "role": item["role"], "match": item["match"], "source": src.name,
            "unit": unit, "unit_len": round(unit_len, 3),
            "gain": round(gain, 4), "offset": offset,
            "normalize_db": round(applied, 2),
        })
        norm.unlink(missing_ok=True)

    if not layers:
        raise PipelineError(f"'{theme}' icin hic ses katmani olusturulamadi.")

    # Miks seviyesini kisa bir probe uzerinden olc: saat boyunca ayni tekrar oldugu
    # icin 180 sn'lik olcum tam saatlik olcumle ayni sonucu verir, ama cok daha hizli.
    probe = work / "probe.wav"
    probe_len = min(180.0, total)
    render_mix(layers, probe, probe_len, sr, 0.0, 0.0, 0.0, acfg["bitrate"])
    measured = measure_lufs(probe, float(acfg["target_lufs"]))
    correction = float(acfg["target_lufs"]) - measured
    probe.unlink(missing_ok=True)
    log.info("Miks: %.1f LUFS  ->  duzeltme %+.1f dB", measured, correction)

    out = work / "audio.m4a"
    render_mix(
        layers, out, total, sr, correction,
        float(acfg["fade_in_sec"]), float(acfg["fade_out_sec"]), acfg["bitrate"],
    )

    qc = work / "qc_seam.wav"
    seam_at = seam_clip(out, qc, layers[0]["unit_len"])
    if seam_at:
        log.info("QC kesiti: %s  (ek noktasi %.0f. sn)", qc.name, seam_at)

    recipe = {
        "layers": [{k: v for k, v in l.items() if k != "unit"} for l in layers],
        "crossfade_sec": xfade,
        "target_lufs": float(acfg["target_lufs"]),
        "mix_correction_db": round(correction, 2),
        "duration_sec": round(total, 1),
        "seam_check_sec": seam_at,
    }
    log.info("Ses hazir: %s (%.1f MB)", out.name, out.stat().st_size / 1e6)
    return {"path": out, "qc": qc if seam_at else None, "recipe": recipe}
