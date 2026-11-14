import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import ai  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)


@pytest.fixture(autouse=True)
def no_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
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


def test_explain_uses_ai_when_available(monkeypatch):
    calls = []

    class FakeMessages:
        def create(self, **kw):
            calls.append(kw)
            return SimpleNamespace(content=[SimpleNamespace(type="text", text="Fake AI explanation.")])

    monkeypatch.setattr(ai, "_client", lambda: SimpleNamespace(messages=FakeMessages()))
    body = {"target_id": "gale", "candidate_id": "dry_valleys"}
    r = client.post("/api/explain", json=body)
    assert r.json()["source"] == "ai" and r.json()["explanation"] == "Fake AI explanation."
    assert len(calls) == 1 and "similarity_percent" in calls[0]["messages"][0]["content"]
    client.post("/api/explain", json=body)
    assert len(calls) == 1  # second request served from cache


def test_explain_survives_ai_failure(monkeypatch):
    class Boom:
        class messages:
            @staticmethod
            def create(**kw):
                raise RuntimeError("network down")

    monkeypatch.setattr(ai, "_client", lambda: Boom())
    r = client.post("/api/explain", json={"target_id": "gale", "candidate_id": "uyuni"})
    assert r.status_code == 200 and r.json()["source"] == "template"
