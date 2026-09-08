"""Baslik / aciklama / etiket uretimi — Claude API (Bolum 9) + cevirileri (Bolum 16.3).

Yapilandirilmis cikti (output_config.format) kullaniliyor: model serbest metin degil,
semaya uyan JSON dondurmek zorunda — "JSON parse edilemedi" hatasi olusmuyor.

Maliyet: gunde 1 cagri, ~2k girdi + ~3k cikti token. claude-opus-5 fiyatiyla
kabaca 0,08 $/gun ~ 2,5 $/ay. (Plandaki "1 $ alti" tahmini cevirilerden once yapilmisti.)
Daha ucuz isteniyorsa config'de metadata.model: claude-sonnet-5 yeterli kalitede olur.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from util import REPO, PipelineError, history, log

DEFAULT_MODEL = "claude-opus-5"

LOCALE_NAMES = {
    "es": "Spanish", "pt": "Portuguese (Brazil)", "de": "German",
    "fr": "French", "ja": "Japanese", "it": "Italian", "ko": "Korean",
    "tr": "Turkish", "nl": "Dutch", "pl": "Polish",
}

CREDIT_LINE = "Audio: CC0 field recordings, mixed exclusively for this channel."


def _schema(locales: List[str], max_title: int) -> Dict[str, Any]:
    loc_props = {
        code: {
            "type": "object",
            "properties": {
                "title": {"type": "string", "maxLength": max_title},
                "description": {"type": "string"},
            },
            "required": ["title", "description"],
            "additionalProperties": False,
        }
        for code in locales
    }
    return {
        "type": "object",
        "properties": {
            "title": {"type": "string", "maxLength": max_title},
            "description": {"type": "string"},
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 10,
                "maxItems": 15,
            },
            "localizations": {
                "type": "object",
                "properties": loc_props,
                "required": list(locales),
                "additionalProperties": False,
            },
        },
        "required": ["title", "description", "tags", "localizations"],
        "additionalProperties": False,
    }


def _prompt(
    theme: str, cfg: Dict[str, Any], audio_recipe: Dict[str, Any],
    video_recipe: Dict[str, Any], season_hint: Optional[str],
) -> str:
    mcfg = cfg["metadata"]
    tcfg = cfg["themes"][theme]

    mix = ", ".join(
        f"{l['match'].replace('_', ' ')} at {round(l['gain'] * 100)}%"
        for l in audio_recipe["layers"]
    )
    visual = {
        "clip": "a slow cinematic video loop",
        "photo": "a still photograph with a very slow zoom",
    }.get(video_recipe.get("visual_kind"), "a slow visual loop")

    recent = [e.get("title", "") for e in history()[-int(mcfg["recent_titles_shown"]):]]
    recent_block = "\n".join(f"- {t}" for t in recent if t) or "- (none yet)"

    locales = list(mcfg.get("locales") or [])
    template = (REPO / "prompts" / "metadata_prompt.txt").read_text(encoding="utf-8")
    return template.format(
        channel_name=cfg["channel"]["name"],
        theme=theme.replace("_", " "),
        purpose=tcfg.get("purpose", ""),
        duration_min=int(cfg["audio"]["duration_min"]),
        mix_description=mix,
        visual_description=visual,
        playlist_name=tcfg.get("playlist_name", ""),
        season_line=f"Seasonal angle to lean into: {season_hint}\n" if season_hint else "",
        recent_titles=recent_block,
        max_title_chars=int(mcfg["max_title_chars"]),
        max_tags_chars=int(mcfg["max_tags_chars"]),
        locale_names=", ".join(LOCALE_NAMES.get(c, c) for c in locales),
    )


def _trim_tags(tags: List[str], limit: int) -> List[str]:
    """YouTube toplam etiket karakter sinirini asma (virguller dahil sayilir)."""
    kept: List[str] = []
    total = 0
    for tag in tags:
        cost = len(tag) + (1 if kept else 0)
        if total + cost > limit:
            break
        kept.append(tag)
        total += cost
    return kept


def duration_label(minutes: int) -> str:
    """60 dk -> "1 Hour", 90 dk -> "1.5 Hours", 45 dk -> "45 Minutes".

    Tam bolme kullanilmiyor: 60'in alti "0 Hour" veriyordu.
    """
    if minutes < 60:
        return f"{minutes} Minutes"
    hours = minutes / 60
    if hours.is_integer():
        h = int(hours)
        return f"{h} Hour" if h == 1 else f"{h} Hours"
    return f"{hours:.1f} Hours"


def _fallback(theme: str, cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Bolum 16.8 — Claude erisilemezse gun bos gecmesin. Kalite duser, yayin durmaz."""
    tcfg = cfg["themes"][theme]
    pretty = theme.replace("_", " ").title()
    purpose = (tcfg.get("purpose", "Relaxation").split(",")[0]).strip().lower()
    minutes = int(cfg["audio"]["duration_min"])
    log.warning("Metadata sablonu kullanildi (Claude API erisilemedi).")
    layers = [l["match"].replace("_", " ") for l in (cfg.get("_layers") or [])]
    layer_line = ", ".join(layers) if layers else theme.replace("_", " ")
    label = duration_label(minutes).lower()
    subject = theme.replace("_", " ")

    description = "\n".join([
        f"{duration_label(minutes)} of continuous {subject}. No music, no voices, "
        f"no sudden events — the same weather from start to finish.",
        "",
        "WHAT'S IN THIS HOUR" if minutes == 60 else "WHAT'S IN THIS RECORDING",
        f"– {layer_line}",
        "– Layered and mixed for this video, not a single raw clip",
        "– Looped so the seam is inaudible",
        "– No interruptions, no fades in the middle, no narration",
        "",
        "GOOD FOR",
        "– Falling asleep and staying asleep",
        "– Reading or studying for long stretches",
        "– Focused work that needs a steady background",
        "– Quieting a room that feels too silent",
        "– Long journeys and travel",
        "",
        "Built from real field recordings, layered and mixed for this video, then "
        "looped so the join is inaudible. Nothing here is narrated or scripted.",
        "",
        CREDIT_LINE,
        "",
        f"#{subject.replace(' ', '')} #sleepsounds #naturesounds #ambient #whitenoise "
        f"#{label.replace(' ', '')}",
    ])

    return {
        "title": f"{pretty} Sounds for {purpose.title()} | {duration_label(minutes)}",
        "description": description,
        "tags": _trim_tags(
            [f"{theme.replace('_', ' ')} sounds", "sleep sounds", "relaxing sounds",
             "nature sounds", "white noise", "study music", "focus sounds",
             "ambient sounds", duration_label(minutes).lower(), "calm"],
            int(cfg["metadata"]["max_tags_chars"]),
        ),
        "localizations": {},
        "generated_by": "fallback_template",
    }


def generate(
    theme: str, cfg: Dict[str, Any], audio_recipe: Dict[str, Any],
    video_recipe: Dict[str, Any], season_hint: Optional[str] = None,
    api_key: Optional[str] = None,
) -> Dict[str, Any]:
    mcfg = cfg["metadata"]
    model = mcfg.get("model") or DEFAULT_MODEL
    locales = list(mcfg.get("locales") or [])
    max_title = int(mcfg["max_title_chars"])

    # Sablon, mikste gercekten kullanilan katmanlari yazabilsin diye tarifi gecir.
    cfg = dict(cfg, _layers=audio_recipe.get("layers", []))

    if not api_key:
        return _fallback(theme, cfg)

    try:
        import anthropic

        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=model,
            max_tokens=16000,
            thinking={"type": "adaptive"},
            output_config={
                "effort": "medium",
                "format": {"type": "json_schema", "schema": _schema(locales, max_title)},
            },
            messages=[{
                "role": "user",
                "content": _prompt(theme, cfg, audio_recipe, video_recipe, season_hint),
            }],
        )
        if response.stop_reason == "refusal":
            raise PipelineError(f"Model istegi reddetti: {response.stop_details}")

        text = next(b.text for b in response.content if b.type == "text")
        data = json.loads(text)
        data["generated_by"] = model
        log.info("Metadata: %s tokens in / %s out",
                 response.usage.input_tokens, response.usage.output_tokens)

    except Exception as exc:                       # Bolum 16.8 plan B
        log.warning("Claude API hatasi (%s) — sablona dusuluyor.", exc)
        return _fallback(theme, cfg)

    # Sabit kaynak satiri: Content ID itirazlarinda kanit (Bolum 9).
    if CREDIT_LINE not in data["description"]:
        data["description"] = data["description"].rstrip() + "\n\n" + CREDIT_LINE

    data["title"] = data["title"][:max_title].rstrip()
    data["tags"] = _trim_tags(data["tags"], int(mcfg["max_tags_chars"]))

    log.info("Baslik: %s", data["title"])
    log.info("Etiket: %d adet, %d karakter",
             len(data["tags"]), sum(len(t) for t in data["tags"]) + len(data["tags"]) - 1)
    return data
