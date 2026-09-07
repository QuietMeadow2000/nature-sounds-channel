"""Gorsel pipeline'i: kisa klipten 60 dakikalik dongu (Bolum 7).

Oncelik sirasi:  AI klip kutuphanesi  ->  Pexels stok video  ->  Ken Burns fotograf.

Dongu yontemi ses tarafiyla ayni mantikta: klibin son X saniyesi basina xfade ile
bindirilir, olusan birim -stream_loop ile 60 dk'ya uzatilir. `reverse` (ping-pong)
kasitli olarak kullanilmiyor: tum kareleri RAM'de tutar, 1080p'de runner'i sisirir.

Tekrar eden goruntuyu kirmak icin saat boyunca cok yavas bir renk/parlaklik kaymasi
uygulanir (tek filtre, ek render maliyeti yok) — her dakika pikselde farkli olur.
"""
from __future__ import annotations

import array
import math
import random
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from util import PipelineError, _tool, duration_sec, ffmpeg, ffprobe_json, log

PHOTO_EXTS = (".jpg", ".jpeg", ".png", ".webp")
CLIP_EXTS = (".mp4", ".mov", ".mkv", ".webm")


def _probe_video(path: Path) -> Tuple[int, int, float]:
    info = ffprobe_json(path, streams="v")
    streams = info.get("streams") or []
    if not streams:
        raise PipelineError(f"{path.name}: video akisi yok")
    st = streams[0]
    return int(st["width"]), int(st["height"]), duration_sec(path, streams="v")


def motion_score(path: Path, samples: int = 4) -> float:
    """Kare-kare ortalama fark (0-255). Sabit kamera ~1, kaydirmali cekim ~12.

    Iki sey icin onemli: kaydirmali cekim 19 saniyede bir basa sarinca dongu goze
    batiyor, ve hareket sikistirmanin en pahali kismi — ayni CRF'te sabit kamera
    0.96 Mbps, drone cekimi 12.9 Mbps verdi.
    """
    try:
        dur = duration_sec(path, streams="v")
    except PipelineError:
        return 999.0
    step = 1.0 / 24
    diffs = []
    for i in range(samples):
        t = dur * (i + 1) / (samples + 1)
        pair = []
        for offset in (0.0, step):
            out = subprocess.run(
                [_tool("ffmpeg"), "-hide_banner", "-loglevel", "error",
                 "-ss", f"{t + offset:.4f}", "-i", str(path), "-frames:v", "1",
                 "-vf", "scale=160:90,format=gray", "-f", "rawvideo", "-"],
                capture_output=True).stdout
            pair.append(out)
        if len(pair[0]) < 160 * 90 or len(pair[1]) < 160 * 90:
            continue
        a = array.array("B", pair[0][:160 * 90])
        b = array.array("B", pair[1][:160 * 90])
        diffs.append(sum(abs(x - y) for x, y in zip(a, b)) / len(a))
    return sum(diffs) / len(diffs) if diffs else 999.0


def _scale_pad(w: int, h: int) -> str:
    """Her kaynagi tam olarak WxH'ye getir: en-boy koru, kirp degil, siyahla doldur."""
    return (
        f"scale={w}:{h}:force_original_aspect_ratio=increase,"
        f"crop={w}:{h},setsar=1"
    )


# ---------------------------------------------------------------- kaynak secimi

def pick_source(
    theme: str, assets: Path, cfg: Dict[str, Any], rng: random.Random,
    pexels_key: Optional[str], work: Path,
) -> Dict[str, Any]:
    """Bolum 7 oncelik sirasina gore bir gorsel kaynak sec/indir."""
    clips_dir = assets / "clips" / theme
    if clips_dir.is_dir():
        clips = [p for p in sorted(clips_dir.iterdir()) if p.suffix.lower() in CLIP_EXTS]
        if clips:
            chosen = rng.choice(clips)
            log.info("Gorsel kaynagi: AI klip kutuphanesi (%s)", chosen.name)
            return {"kind": "clip", "path": chosen, "source": chosen.name}

    if pexels_key:
        try:
            import pexels
            queries = cfg["themes"][theme].get("pexels_queries") or [theme]
            n = int(cfg["video"].get("pexels_candidates", 3))
            # rng'yi gecmek sart: gecmeden secim rastgele olur ve --replay ayni
            # videoyu uretemez (Bolum 16.5).
            hits = pexels.fetch_candidates(rng.choice(queries), pexels_key, work, rng, n)
            if hits:
                scored = sorted(((motion_score(h["path"]), h) for h in hits),
                                key=lambda x: x[0])
                for score, h in scored:
                    log.info("  aday %-18s hareket %.1f", h["source"], score)
                best_score, best = scored[0]
                for _, other in scored[1:]:           # secilmeyenleri hemen sil
                    other["path"].unlink(missing_ok=True)
                log.info("Gorsel kaynagi: Pexels (%s, hareket %.1f — en sakin aday)",
                         best["source"], best_score)
                return best
        except Exception as exc:                      # Bolum 16.8 — plan B'ye dus
            log.warning("Pexels basarisiz, yedege geciliyor: %s", exc)

    photos_dir = assets / "photos" / theme
    if photos_dir.is_dir():
        photos = [p for p in sorted(photos_dir.iterdir()) if p.suffix.lower() in PHOTO_EXTS]
        if photos:
            chosen = rng.choice(photos)
            log.info("Gorsel kaynagi: Ken Burns fotograf (%s)", chosen.name)
            return {"kind": "photo", "path": chosen, "source": chosen.name}

    raise PipelineError(
        f"'{theme}' icin hicbir gorsel kaynak yok: klip yok, Pexels basarisiz, fotograf yok.\n"
        f"En az bir yedek gerekli: {photos_dir}/*.jpg"
    )


# ---------------------------------------------------------------- dongu birimi

def clip_loop_unit(src: Path, dst: Path, cfg: Dict[str, Any], xfade: float = 1.5) -> float:
    """Klibin sonunu basina xfade ile bindirerek dikissiz dongu birimi uret."""
    vcfg = cfg["video"]
    w, h, fps = int(vcfg["width"]), int(vcfg["height"]), int(vcfg["fps"])
    _, _, dur = _probe_video(src)

    if dur < xfade * 3:
        raise PipelineError(f"{src.name}: {dur:.1f} sn cok kisa (en az {xfade * 3:.0f} sn)")
    xfade = min(xfade, dur / 4)
    head_end = dur - xfade

    chain = (
        f"[0:v]fps={fps},{_scale_pad(w, h)},format=yuv420p,split=2[a][b];"
        f"[a]trim=0:{head_end:.4f},setpts=PTS-STARTPTS[a1];"
        f"[b]trim={head_end:.4f}:{dur:.4f},setpts=PTS-STARTPTS[b1];"
        f"[b1][a1]xfade=transition=fade:duration={xfade:.4f}:offset=0[out]"
    )
    ffmpeg(
        ["-i", str(src), "-filter_complex", chain, "-map", "[out]",
         "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
         "-pix_fmt", "yuv420p", str(dst)],
        f"dongu birimi {src.name}",
    )
    unit_len = duration_sec(dst, streams="v")
    log.info("  klip %.1f sn  ->  dongu birimi %.1f sn (xfade %.1f sn)", dur, unit_len, xfade)
    return unit_len


def kenburns_unit(src: Path, dst: Path, cfg: Dict[str, Any], seconds: float = 60.0) -> float:
    """Fotograftan yavas zoom in/out birimi — bas ve son kare ayni, dikissiz doner."""
    vcfg = cfg["video"]
    w, h, fps = int(vcfg["width"]), int(vcfg["height"]), int(vcfg["fps"])
    frames = int(seconds * fps)
    # z, on=0 ve on=frames'te ayni degeri alir -> dongu ek yeri gorunmez.
    zoom = f"1.05+0.05*cos(2*PI*on/{frames})"
    chain = (
        f"scale={w * 2}:{h * 2}:force_original_aspect_ratio=increase,crop={w * 2}:{h * 2},"
        f"zoompan=z='{zoom}':d={frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
        f":s={w}x{h}:fps={fps},format=yuv420p"
    )
    ffmpeg(
        ["-loop", "1", "-i", str(src), "-t", f"{seconds:.2f}", "-vf", chain,
         "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
         "-pix_fmt", "yuv420p", str(dst)],
        f"ken burns {src.name}",
    )
    log.info("  fotograf  ->  Ken Burns birimi %.0f sn", seconds)
    return duration_sec(dst, streams="v")


# ---------------------------------------------------------------- final render

# Kayma genlikleri (drift=1.0 icin). Kare-kare gorunmez, saat boyunca olculebilir:
# duz renk uzerinde kanal basina ~11/255 degisim. Amac, 288 kez tekrarlanan birimin
# birbirinin bit-bit kopyasi olmamasi (Bolum 11, "tekrar eden icerik" riski).
# Periyotlar birbirine bolunmez secildi ki desen tekrarlanmasin.
DRIFT_HUE_DEG = 5.0        # hue: derece cinsinden — kucuk degerler H.264'te tamamen kaybolur
DRIFT_SAT = 0.05
DRIFT_BRIGHT = 0.015


def drift_filter(scale: float) -> str:
    """Cok yavas renk/parlaklik kaymasi. eq icin eval=frame SART:
    varsayilan eval=init ifadeyi bir kez hesaplar ve kayma sabit kalir."""
    return (
        f"hue=h='{DRIFT_HUE_DEG * scale:.2f}*sin(2*PI*t/2400)'"
        f":s='1+{DRIFT_SAT * scale:.3f}*sin(2*PI*t/1500)',"
        f"eq=brightness='{DRIFT_BRIGHT * scale:.4f}*sin(2*PI*t/1800)':eval=frame"
    )


def render_final(
    unit: Path, unit_len: float, audio: Path, out: Path,
    cfg: Dict[str, Any], drift: Optional[float] = None,
) -> None:
    """Birimi 60 dk'ya uzat, sesi bindir, tek gecis H.264 render."""
    vcfg = cfg["video"]
    total = float(cfg["audio"]["duration_min"]) * 60.0
    loops = max(0, math.ceil(total / unit_len) - 1)
    if drift is None:
        drift = float(vcfg.get("drift", 1.0))

    filters = [f"trim=0:{total:.3f}", "setpts=PTS-STARTPTS"]
    if drift > 0:
        filters.append(drift_filter(drift))
    filters.append("format=yuv420p")

    args = [
        "-stream_loop", str(loops), "-i", str(unit),
        "-i", str(audio),
        "-filter_complex", f"[0:v]{','.join(filters)}[v]",
        "-map", "[v]", "-map", "1:a",
        "-c:v", "libx264",
        "-preset", str(vcfg.get("preset", "veryfast")),
        "-crf", str(vcfg["crf"]),
        "-r", str(vcfg["fps"]),
    ]
    # CRF sabit KALITE demek, sabit boyut degil. Kolay icerikte (bulanik arka planli
    # yagmur) ~1 Mbps cikiyor, zor icerikte (gunes vuran su yuzeyi, binlerce parlama)
    # 13 Mbps'e firliyor ve 60 dakika 5,9 GB oluyor. Tavan sart.
    # YouTube 1080p'yi zaten ~4 Mbps'e yeniden kodluyor; ustune cikmak bosa bit.
    maxrate = float(vcfg.get("maxrate_mbps", 0) or 0)
    if maxrate > 0:
        args += ["-maxrate", f"{maxrate:.1f}M", "-bufsize", f"{maxrate * 2:.1f}M"]
    # tune=stillimage yalnizca goruntu gercekten sabitken kazanc saglar;
    # renk kaymasi acikken dosyayi buyutur, o yuzden atlanir.
    tune = vcfg.get("tune")
    if tune and drift <= 0:
        args += ["-tune", str(tune)]
    args += [
        "-c:a", "copy",
        "-movflags", "+faststart",
        "-shortest",
        str(out),
    ]
    ffmpeg(args, "final render")


def build(
    theme: str, cfg: Dict[str, Any], assets: Path, work: Path, audio: Path,
    seed: int, pexels_key: Optional[str] = None,
) -> Dict[str, Any]:
    rng = random.Random(seed + 1)
    src = pick_source(theme, assets, cfg, rng, pexels_key, work)

    unit = work / "vunit.mp4"
    if src["kind"] == "photo":
        unit_len = kenburns_unit(src["path"], unit, cfg)
    else:
        unit_len = clip_loop_unit(src["path"], unit, cfg)

    out = work / "final.mp4"
    render_final(unit, unit_len, audio, out, cfg)

    size_mb = out.stat().st_size / 1e6
    log.info("Video hazir: %s (%.0f MB)", out.name, size_mb)
    return {
        "path": out,
        "recipe": {
            "visual_kind": src["kind"],
            "visual_source": src["source"],
            "unit_len_sec": round(unit_len, 2),
            "size_mb": round(size_mb, 1),
        },
    }
