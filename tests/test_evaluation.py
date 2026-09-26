import json
from pathlib import Path

from fastapi.testclient import TestClient

from app import create_app
from evals.retrieval_eval import evaluate


def test_benchmark_and_api_routes_match(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    result = evaluate()
    assert result["cases"] == 40
    assert not result["failures"]
    c = TestClient(create_app(tmp_path / "isolated.sqlite"))
    token = c.post("/api/session", json={"person": "alex"}).json()["token"]
    h = {"Authorization": "Bearer " + token}
    for case in result["results"]:
        reply = c.post("/api/chat", headers=h, json={"question": case["question"]}).json()
        if case["expected"] in ("escalate", "unsupported"):
            assert reply["action"] == "escalate"
            assert reply["citations"] == []
        elif case["expected"] == "supported":
            assert case["source"] in reply["citations"]
            assert {p["id"] for p in reply["sources"]} == set(reply["citations"])
            assert all(p["text"] and p["version"] for p in reply["sources"])
    # Escalation tickets retain no question text.
    requests = json.dumps(c.get("/api/requests", headers=h).json())
    assert "harassment" not in requests and "salary" not in requests


def test_citation_passages_are_exact_handbook_sources(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    c = TestClient(create_app(tmp_path / "isolated.sqlite"))
    h = {
        "Authorization": "Bearer " + c.post("/api/session", json={"person": "alex"}).json()["token"]
    }
    source = {
        p["id"]: p for p in json.loads((Path(__file__).parents[1] / "handbook.json").read_text())
    }
    for question in ["What is the parental leave policy?", "How do I request time off?"]:
        reply = c.post("/api/chat", headers=h, json={"question": question}).json()
        assert all(p == source[p["id"]] for p in reply["sources"])
