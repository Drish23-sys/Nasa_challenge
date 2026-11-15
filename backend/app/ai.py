"""AI-written explanations of a match, with a deterministic fallback.

The model is only given numbers and facts that are already in sites.json and is
told not to invent anything. If there is no API key, or the call fails for any
reason, the app falls back to a template so the demo never breaks.

Providers (picked automatically from which key is set; override with AI_PROVIDER):
  gemini     GEMINI_API_KEY (or GOOGLE_API_KEY)   GEMINI_MODEL     default: gemini-3.8-flash
  anthropic  ANTHROPIC_API_KEY                    ANTHROPIC_MODEL  default: claude-sonnet-5-5
  none       (no key) -> template text

Set keys ONLY on the backend host (Render) or your local shell. Never commit them.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import threading

log = logging.getLogger("analog.ai")

GEMINI_DEFAULT = "gemini-3.8-flash"
ANTHROPIC_DEFAULT = "claude-sonnet-5-5"

SYSTEM = (
    "You explain planetary-analog matches for a NASA Space Apps hackathon tool. "
    "Use ONLY the numbers and facts in the JSON you are given. Do not invent measurements, "
    "citations, site facts or mission details. Write 90 to 130 words of plain prose, no markdown, "
    "in three short parts: (1) what matches and how strongly, (2) where the analogy breaks down "
    "- always mention the limits given in target.environment_notes, and radiation - and (3) one "
    "concrete, modest way this site could help prepare for exploring the target; do not claim "
    "more than the data supports. "
    "IMPORTANT: a high per-factor similarity means the two values are CLOSE, not that the factor is "
    "high. Use the 'values' field to say what each side actually has, for example 'both have little "
    "basaltic terrain' or 'the site is much smoother'. The temp_range factor is the SIZE of the "
    "temperature swing, not how warm or cold a place is: never say a site is warmer or colder "
    "unless known_limits says so; say it has a larger or smaller temperature swing instead. "
    "If estimated_factors is not empty, say those factors, named exactly as listed, are estimates "
    "and not measurements. Similarity numbers are percentages where 100 means identical."
)

BODY_NOTES = {
    "Moon": "The Moon has about one sixth of Earth's gravity and essentially no atmosphere (a near-vacuum).",
    "Mars": "Mars has about 38% of Earth's gravity and a very thin carbon-dioxide atmosphere, under 1% of Earth's pressure.",
}

_cache: dict[str, tuple[str, str, str]] = {}
_lock = threading.Lock()


# --------------------------------------------------------------------------- provider selection
def _gemini_key() -> str | None:
    return os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")


def provider() -> str:
    """'gemini', 'anthropic' or 'none'."""
    forced = os.getenv("AI_PROVIDER", "").strip().lower()
    if forced == "none":
        return "none"
    if forced == "gemini":
        return "gemini" if _gemini_key() else "none"
    if forced == "anthropic":
        return "anthropic" if os.getenv("ANTHROPIC_API_KEY") else "none"
    if _gemini_key():
        return "gemini"
    if os.getenv("ANTHROPIC_API_KEY"):
        return "anthropic"
    return "none"


def model_name(prov: str | None = None) -> str | None:
    prov = prov or provider()
    if prov == "gemini":
        return os.getenv("GEMINI_MODEL", GEMINI_DEFAULT)
    if prov == "anthropic":
        return os.getenv("ANTHROPIC_MODEL", ANTHROPIC_DEFAULT)
    return None


def status() -> dict:
    prov = provider()
    return {"ai_configured": prov != "none", "ai_provider": prov, "model": model_name(prov)}


# --------------------------------------------------------------------------- provider calls
def _call_gemini(system: str, user: str, model: str) -> str:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=_gemini_key())
    resp = client.models.generate_content(
        model=model,
        contents=user,
        config=types.GenerateContentConfig(
            system_instruction=system,
            temperature=0.4,
            # generous limit: some Gemini models spend part of the budget on internal "thinking"
            max_output_tokens=1500,
            http_options=types.HttpOptions(timeout=25000),  # milliseconds
        ),
    )
    return (resp.text or "").strip()


def _call_anthropic(system: str, user: str, model: str) -> str:
    import anthropic

    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"), timeout=25.0, max_retries=1)
    resp = client.messages.create(
        model=model, max_tokens=400, system=system, messages=[{"role": "user", "content": user}]
    )
    return "".join(b.text for b in resp.content if getattr(b, "type", "text") == "text").strip()


# --------------------------------------------------------------------------- payload + template
def build_payload(target: dict, cand: dict, result: dict) -> dict:
    estimated = sorted(
        {f for f, v in target.get("confidence", {}).items() if v == "estimated"}
        | {f for f, v in cand.get("confidence", {}).items() if v == "estimated"}
    )
    return {
        "target": {
            "name": target["name"], "body": target["body"], "blurb": target.get("blurb", ""),
            "factors": target["factors"],
            "environment_notes": BODY_NOTES.get(target["body"], ""),
        },
        "values": {f: {"target": round(target["factors"][f], 2), "site": round(cand["factors"][f], 2)}
                   for f in target["factors"]},
        "earth_site": {
            "name": cand["name"], "type": cand["type"], "features": cand.get("features", []),
            "factors": cand["factors"], "why_it_is_an_analog": cand.get("why", ""),
            "known_limits": cand.get("breaks_down", ""),
        },
        "similarity_percent": {
            "overall": round(result["score"] * 100),
            "per_factor": {f: round(v * 100) for f, v in result["breakdown"].items()},
        },
        "weights": {f: round(v, 3) for f, v in result["weights"].items()},
        "estimated_factors": estimated,
    }


def template_explanation(payload: dict) -> str:
    per = payload["similarity_percent"]["per_factor"]
    best = sorted(per, key=per.get, reverse=True)[:2]
    worst = min(per, key=per.get)
    t, s = payload["target"], payload["earth_site"]
    label = lambda f: f.replace("_", " ")
    text = (
        f"{s['name']} matches {t['name']} at {payload['similarity_percent']['overall']}% overall. "
        f"The strongest agreement is in {label(best[0])} ({per[best[0]]}%) and {label(best[1])} "
        f"({per[best[1]]}%); the weakest is {label(worst)} ({per[worst]}%). "
        f"{s['why_it_is_an_analog']} {s['known_limits']} "
        f"Like every Earth analog, it cannot reproduce the target's conditions: {t['environment_notes']} "
        "Nor can it reproduce the radiation environment."
    )
    if payload["estimated_factors"]:
        text += " Some factor values are estimates, not measurements."
    return " ".join(text.split())


# --------------------------------------------------------------------------- main entry
def explain(target: dict, cand: dict, result: dict) -> tuple[str, str, str | None]:
    """Return (text, source, model). source is 'ai' or 'template'."""
    payload = build_payload(target, cand, result)
    prov = provider()
    model = model_name(prov)
    key = hashlib.sha256(json.dumps([prov, model, payload], sort_keys=True).encode()).hexdigest()
    with _lock:
        if key in _cache:
            text, source, used = _cache[key]
            return text, source, used or None

    if prov != "none":
        try:
            call = _call_gemini if prov == "gemini" else _call_anthropic
            text = call(SYSTEM, json.dumps(payload, indent=2), model)
            if text:
                with _lock:
                    _cache[key] = (text, "ai", model)
                return text, "ai", model
            log.warning("AI returned empty text (%s/%s), using template", prov, model)
        except Exception as exc:  # network, bad key, wrong model name, rate limit, anything
            log.warning("AI explanation failed (%s/%s), using template: %s", prov, model, exc)

    text = template_explanation(payload)
    return text, "template", None