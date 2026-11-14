"""AI-written explanations of a match, with a deterministic fallback.

The model is only given numbers and facts that are already in sites.json and is
told not to invent anything. If there is no API key, or the call fails for any
reason, the app falls back to a template so the demo never breaks.

Env vars:
  ANTHROPIC_API_KEY  - set ONLY on the backend host (Render). Never commit it.
  ANTHROPIC_MODEL    - defaults to claude-sonnet-5-5
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import threading

log = logging.getLogger("analog.ai")

MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5-5")

SYSTEM = (
    "You explain planetary-analog matches for a NASA Space Apps hackathon tool. "
    "Use ONLY the numbers and facts in the JSON you are given. Do not invent measurements, "
    "citations, site facts or mission details. Write 90 to 130 words of plain prose, no markdown, "
    "in three short parts: (1) what matches and how strongly, (2) where the analogy breaks down "
    "- always mention that Earth cannot reproduce reduced gravity, vacuum or thin atmosphere, and "
    "radiation - and (3) one concrete way this site could help prepare for exploring the target. "
    "If a factor is listed under estimated_factors, say that value is an estimate. "
    "Similarity numbers are percentages where 100 means identical."
)

_cache: dict[str, tuple[str, str]] = {}
_lock = threading.Lock()


def _client():
    key = os.getenv("ANTHROPIC_API_KEY")
    if not key:
        return None
    import anthropic

    return anthropic.Anthropic(api_key=key, timeout=25.0, max_retries=1)


def build_payload(target: dict, cand: dict, result: dict) -> dict:
    estimated = sorted(
        {f for f, v in target.get("confidence", {}).items() if v == "estimated"}
        | {f for f, v in cand.get("confidence", {}).items() if v == "estimated"}
    )
    return {
        "target": {
            "name": target["name"], "body": target["body"], "blurb": target.get("blurb", ""),
            "factors": target["factors"],
        },
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
        "Like every Earth analog, it cannot reproduce reduced gravity, vacuum or a thin atmosphere, "
        "or the radiation environment."
    )
    if payload["estimated_factors"]:
        text += " Some factor values are estimates, not measurements."
    return " ".join(text.split())


def explain(target: dict, cand: dict, result: dict) -> tuple[str, str, str | None]:
    """Return (text, source, model). source is 'ai' or 'template'."""
    payload = build_payload(target, cand, result)
    key = hashlib.sha256(json.dumps([MODEL, payload], sort_keys=True).encode()).hexdigest()
    with _lock:
        if key in _cache:
            text, source = _cache[key]
            return text, source, MODEL if source == "ai" else None

    client = _client()
    if client is not None:
        try:
            resp = client.messages.create(
                model=MODEL,
                max_tokens=400,
                system=SYSTEM,
                messages=[{"role": "user", "content": json.dumps(payload, indent=2)}],
            )
            text = "".join(b.text for b in resp.content if getattr(b, "type", "text") == "text").strip()
            if text:
                with _lock:
                    _cache[key] = (text, "ai")
                return text, "ai", MODEL
        except Exception as exc:  # network, auth, rate limit, anything
            log.warning("AI explanation failed, using template: %s", exc)

    text = template_explanation(payload)
    return text, "template", None
