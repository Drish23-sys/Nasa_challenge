"""Explainable similarity scoring.

Per-factor similarity = 1 - |target - candidate|   (all factors normalized 0-1)
Overall score         = weighted average of the per-factor similarities

The same maths lives in frontend/scoring.js so the sliders re-rank instantly in
the browser. backend/tests/test_scoring.py and scripts/check_js_parity.py keep
the two implementations identical.
"""
from __future__ import annotations

FACTORS = ("slope", "roughness", "temp_range", "aridity", "basaltic")


def clean_weights(weights: dict | None = None) -> dict:
    """Validate and normalize weights so they sum to 1. Missing factors default to 1."""
    if weights:
        unknown = set(weights) - set(FACTORS)
        if unknown:
            raise ValueError(f"unknown factor(s): {sorted(unknown)}")
    raw = {}
    for f in FACTORS:
        v = 1.0 if not weights or f not in weights else float(weights[f])
        if v != v or v < 0 or v == float("inf"):
            raise ValueError(f"invalid weight for {f}: {v}")
        raw[f] = v
    total = sum(raw.values())
    if total <= 0:
        raise ValueError("at least one weight must be greater than zero")
    return {f: raw[f] / total for f in FACTORS}


def score_pair(target_factors: dict, cand_factors: dict, weights: dict | None = None) -> dict:
    w = clean_weights(weights)
    breakdown = {f: 1.0 - abs(target_factors[f] - cand_factors[f]) for f in FACTORS}
    score = 0.0
    for f in FACTORS:  # explicit loop (not sum()) so floats match the JavaScript version exactly
        score += w[f] * breakdown[f]
    return {"score": score, "breakdown": breakdown, "weights": w}


def rank(target: dict, candidates: list[dict], weights: dict | None = None,
         types: list[str] | None = None, top_n: int | None = None) -> list[dict]:
    """Rank candidates against one target, best first. Ties break on name."""
    wanted = set(types) if types else None
    out = []
    for c in candidates:
        if wanted and c["type"] not in wanted:
            continue
        r = score_pair(target["factors"], c["factors"], weights)
        out.append({
            "id": c["id"], "name": c["name"], "type": c["type"],
            "lat": c["lat"], "lon": c["lon"], "features": c.get("features", []),
            "score": r["score"], "breakdown": r["breakdown"],
        })
    # round for the sort key so float noise (0.89 vs 0.8900000000000001) never reorders ties
    out.sort(key=lambda x: (-round(x["score"], 9), x["name"]))
    if top_n:
        out = out[:top_n]
    for i, item in enumerate(out, 1):
        item["rank"] = i
    return out
