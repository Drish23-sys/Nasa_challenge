import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import ai  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)


@pytest.fixture(autouse=True)
def no_key(monkeypatch):
    for k in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY", "AI_PROVIDER", "GEMINI_MODEL"):
        monkeypatch.delenv(k, raising=False)
    ai._cache.clear()


def test_health():
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_lists():
    assert len(client.get("/api/targets").json()) >= 3
    assert len(client.get("/api/candidates").json()) >= 15


def test_rank_is_descending_and_explainable():
    r = client.post("/api/rank", json={"target_id": "jezero", "top_n": 5})
    assert r.status_code == 200
    res = r.json()["results"]
    assert len(res) == 5
    scores = [x["score"] for x in res]
    assert scores == sorted(scores, reverse=True)
    assert set(res[0]["breakdown"]) == {"slope", "roughness", "temp_range", "aridity", "basaltic"}


def test_rank_errors():
    assert client.post("/api/rank", json={"target_id": "nope"}).status_code == 404
    assert client.post("/api/rank", json={"target_id": "jezero", "weights": {"bad": 1}}).status_code == 422


def test_explain_falls_back_to_template_without_key():
    r = client.post("/api/explain", json={"target_id": "jezero", "candidate_id": "atacama"})
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "template" and body["model"] is None
    assert "Atacama" in body["explanation"]


def test_provider_selection(monkeypatch):
    assert ai.provider() == "none" and ai.status()["ai_configured"] is False
    monkeypatch.setenv("ANTHROPIC_API_KEY", "a")
    assert ai.provider() == "anthropic"
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    assert ai.provider() == "gemini"           # Gemini wins when both are set
    monkeypatch.setenv("AI_PROVIDER", "anthropic")
    assert ai.provider() == "anthropic"
    monkeypatch.setenv("AI_PROVIDER", "none")
    assert ai.provider() == "none"
    monkeypatch.setenv("AI_PROVIDER", "gemini")
    monkeypatch.delenv("GEMINI_API_KEY")
    assert ai.provider() == "none"              # forced provider without its key -> template


def test_health_reports_ai_status(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    monkeypatch.setenv("GEMINI_MODEL", "my-model")
    body = client.get("/api/health").json()
    assert body["ai_configured"] is True and body["ai_provider"] == "gemini" and body["model"] == "my-model"


def test_explain_uses_gemini_and_caches(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    calls = []

    def fake(system, user, model):
        calls.append((system, user, model))
        return "Fake Gemini explanation."

    monkeypatch.setattr(ai, "_call_gemini", fake)
    body = {"target_id": "gale", "candidate_id": "dry_valleys"}
    r = client.post("/api/explain", json=body)
    j = r.json()
    assert j["source"] == "ai" and j["explanation"] == "Fake Gemini explanation." and j["model"] == ai.GEMINI_DEFAULT
    assert len(calls) == 1 and "similarity_percent" in calls[0][1] and "ONLY" in calls[0][0]
    client.post("/api/explain", json=body)
    assert len(calls) == 1  # second request served from cache


def test_explain_uses_anthropic_when_only_that_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "a")
    monkeypatch.setattr(ai, "_call_anthropic", lambda s, u, m: "Fake Claude explanation.")
    j = client.post("/api/explain", json={"target_id": "gale", "candidate_id": "atacama"}).json()
    assert j["source"] == "ai" and j["model"] == ai.ANTHROPIC_DEFAULT


@pytest.mark.parametrize("behavior", ["raise", "empty"])
def test_explain_survives_ai_failure(monkeypatch, behavior):
    monkeypatch.setenv("GEMINI_API_KEY", "g")

    def bad(system, user, model):
        if behavior == "raise":
            raise RuntimeError("404 model not found")
        return ""

    monkeypatch.setattr(ai, "_call_gemini", bad)
    r = client.post("/api/explain", json={"target_id": "gale", "candidate_id": "uyuni"})
    assert r.status_code == 200 and r.json()["source"] == "template" and r.json()["model"] is None
