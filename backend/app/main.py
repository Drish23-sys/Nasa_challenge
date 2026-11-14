"""Earth Analog Finder API.

Run locally:   uvicorn app.main:app --reload --app-dir backend
Docs (Swagger): http://127.0.0.1:8000/docs
"""
from __future__ import annotations

import os
import time
from collections import defaultdict, deque

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import ai, data, scoring

app = FastAPI(title="Earth Analog Finder API", version="1.0.0")

origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["*"], allow_headers=["*"])

# --- tiny in-memory rate limit for /api/explain (protects your API key) -------------
EXPLAIN_LIMIT = int(os.getenv("EXPLAIN_RATE_LIMIT", "30"))  # per IP per hour
_hits: dict[str, deque] = defaultdict(deque)


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _check_rate(request: Request) -> None:
    now, ip = time.time(), _client_ip(request)
    q = _hits[ip]
    while q and now - q[0] > 3600:
        q.popleft()
    if len(q) >= EXPLAIN_LIMIT:
        raise HTTPException(429, "Too many explanation requests, try again later")
    q.append(now)


# --- schemas ------------------------------------------------------------------------
class RankRequest(BaseModel):
    target_id: str
    weights: dict[str, float] | None = None
    types: list[str] | None = None
    top_n: int | None = Field(default=None, ge=1, le=100)


class ExplainRequest(BaseModel):
    target_id: str
    candidate_id: str
    weights: dict[str, float] | None = None


def _need_target(target_id: str) -> dict:
    t = data.get_target(target_id)
    if not t:
        raise HTTPException(404, f"unknown target '{target_id}'")
    return t


# --- routes -------------------------------------------------------------------------
@app.get("/api/health")
def health():
    meta = data.load()["meta"]
    return {"status": "ok", "data_version": meta.get("version"), "ai_configured": bool(os.getenv("ANTHROPIC_API_KEY")),
            "model": ai.MODEL}


@app.get("/api/data")
def all_data():
    return data.load()


@app.get("/api/meta")
def meta():
    return data.load()["meta"]


@app.get("/api/targets")
def targets():
    return data.load()["targets"]


@app.get("/api/candidates")
def candidates():
    return data.load()["candidates"]


@app.post("/api/rank")
def rank(req: RankRequest):
    target = _need_target(req.target_id)
    try:
        results = scoring.rank(target, data.load()["candidates"], req.weights, req.types, req.top_n)
        weights = scoring.clean_weights(req.weights)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    return {"target": req.target_id, "weights": weights, "results": results}


@app.post("/api/explain")
def explain(req: ExplainRequest, request: Request):
    target = _need_target(req.target_id)
    cand = data.get_candidate(req.candidate_id)
    if not cand:
        raise HTTPException(404, f"unknown candidate '{req.candidate_id}'")
    try:
        result = scoring.score_pair(target["factors"], cand["factors"], req.weights)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    _check_rate(request)
    text, source, model = ai.explain(target, cand, result)
    return {"explanation": text, "source": source, "model": model,
            "score": result["score"], "breakdown": result["breakdown"]}


# Serve the reference frontend from the same service if the folder exists.
# (Optional: lets you deploy everything on Render alone. Must stay LAST.)
_frontend = data.ROOT / "frontend"
if _frontend.is_dir():
    app.mount("/", StaticFiles(directory=_frontend, html=True), name="frontend")
