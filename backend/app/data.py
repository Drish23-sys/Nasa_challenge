"""Loads data/sites.json (rebuilt automatically if the file changes on disk)."""
from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_PATH = Path(os.getenv("DATA_PATH", ROOT / "data" / "sites.json"))

_cache = {"mtime": None, "data": None}


def load() -> dict:
    mtime = DATA_PATH.stat().st_mtime
    if _cache["mtime"] != mtime:
        with open(DATA_PATH, encoding="utf-8") as fh:
            _cache["data"] = json.load(fh)
        _cache["mtime"] = mtime
    return _cache["data"]


def get_target(target_id: str) -> dict | None:
    return next((t for t in load()["targets"] if t["id"] == target_id), None)


def get_candidate(candidate_id: str) -> dict | None:
    return next((c for c in load()["candidates"] if c["id"] == candidate_id), None)
