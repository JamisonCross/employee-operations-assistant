from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

import ai
from app import create_app, retrieve


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    return TestClient(create_app(tmp_path / "test.sqlite"))


def auth(c, person="alex"):
    return {
        "Authorization": "Bearer " + c.post("/api/session", json={"person": person}).json()["token"]
    }


def leave(key="test-key-123", offset=0, days=1, category="pto"):
    start = date.today() + timedelta(days=7 + offset)
    while start.weekday() != 0:
        start += timedelta(days=1)
    return {
        "category": category,
        "start": str(start),
        "end": str(start + timedelta(days=days - 1)),
        "key": key,
    }


def test_authorization_and_own_balance(client):
    assert client.get("/api/me").status_code == 401
    a = auth(client)
    b = auth(client, "jordan")
    assert client.get("/api/me", headers=a).json()["balance"]["available"] == 120
    assert client.get("/api/me", headers=b).json()["balance"]["available"] == 64
    assert client.get("/api/review", headers=a).status_code == 403
    assert (
        client.post("/api/requests", headers=a, json={**leave(), "person": "jordan"}).status_code
        == 422
    )


def test_request_isolated_and_idempotent(client):
    a = auth(client)
    b = auth(client, "jordan")
    payload = leave()
    first = client.post("/api/requests", json=payload, headers=a).json()
    assert client.post("/api/requests", json=payload, headers=a).json()["id"] == first["id"]
    assert client.get("/api/requests", headers=b).json() == []
    assert client.post("/api/requests", json=leave(days=2), headers=a).status_code == 409
    assert client.post("/api/requests", json=leave(key="another-key"), headers=a).status_code == 409
    assert client.get("/api/me", headers=a).json()["balance"] == {
        "hours": 120,
        "reserved": 8,
        "available": 112,
    }


def test_approval_atomic_and_replay_safe(client):
    a = auth(client)
    s = auth(client, "sam")
    r = client.post("/api/requests", json=leave(), headers=a).json()
    action = lambda: (
        client.post(
            "/api/review/" + str(r["id"]),
            json={"decision": "approve", "note": "Dates reviewed"},
            headers=s,
        ).status_code
    )
    with ThreadPoolExecutor(2) as pool:
        codes = list(pool.map(lambda _: action(), range(2)))
    assert sorted(codes) == [200, 409]
    assert client.get("/api/me", headers=a).json()["balance"] == {
        "hours": 112,
        "reserved": 0,
        "available": 112,
    }


def test_sensitive_and_insufficient_escalate(client):
    a = auth(client)
    s = auth(client, "sam")
    r = client.post("/api/requests", json=leave(category="medical"), headers=a).json()
    assert r["status"] == "escalated" and r["hours"] == 0
    result = client.post(
        "/api/review/" + str(r["id"]),
        json={"decision": "approve", "note": "Private follow-up"},
        headers=s,
    ).json()
    assert result["status"] == "human_followup"
    r = client.post(
        "/api/requests", json=leave(key="long-request", offset=30, days=30), headers=a
    ).json()
    assert r["status"] == "escalated" and r["hours"] == 0
    assert (
        client.post(
            "/api/review/" + str(r["id"]),
            json={"decision": "approve", "note": "Reviewed"},
            headers=s,
        ).status_code
        == 409
    )


def test_reviewer_cannot_approve_self(client):
    s = auth(client, "sam")
    r = client.post("/api/requests", json=leave(), headers=s).json()
    assert (
        client.post(
            "/api/review/" + str(r["id"]),
            json={"decision": "approve", "note": "Mine"},
            headers=s,
        ).status_code
        == 403
    )


@pytest.mark.parametrize(
    "question",
    [
        "What is Jordan’s PTO balance?",
        "Am I eligible for parental leave?",
        "I need a medical accommodation",
    ],
)
def test_sensitive_chat_no_model(client, monkeypatch, question):
    import app

    monkeypatch.setattr(app, "generate", lambda *a: pytest.fail("Sensitive data reached LLM"))
    result = client.post("/api/chat", json={"question": question}, headers=auth(client)).json()
    assert result["action"] == "escalate"


def test_retrieval_and_missing_source(client):
    assert retrieve("parental leave policy")[0]["id"] == "parental"
    a = auth(client)
    assert (
        "parental"
        in client.post(
            "/api/chat",
            json={"question": "What is the parental leave policy?"},
            headers=a,
        ).json()["citations"]
    )
    assert (
        client.post("/api/chat", json={"question": "xyzzy quux zork"}, headers=a).json()["action"]
        == "escalate"
    )
    assert (
        "120 hours"
        in client.post("/api/chat", json={"question": "How much PTO do I have?"}, headers=a).json()[
            "answer"
        ]
    )


def test_bad_dates_and_decline_releases_reservation(client):
    a = auth(client)
    s = auth(client, "sam")
    p = leave()
    p["end"] = "2020-01-01"
    assert client.post("/api/requests", json=p, headers=a).status_code == 422
    r = client.post("/api/requests", json=leave(), headers=a).json()
    assert (
        client.post(
            "/api/review/" + str(r["id"]),
            json={"decision": "decline", "note": "Discuss dates"},
            headers=s,
        ).status_code
        == 200
    )
    assert client.get("/api/me", headers=a).json()["balance"]["available"] == 120


def test_live_contract_and_fallback(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-only")
    import httpx

    def reply(url, **kw):
        assert kw["json"]["store"] is False
        assert kw["json"]["text"]["format"]["strict"] is True
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={
                "status": "completed",
                "output": [
                    {
                        "content": [
                            {
                                "type": "output_text",
                                "text": '{"answer":"Policy answer", "citations":["pto"]}',
                            }
                        ]
                    }
                ],
            },
        )

    monkeypatch.setattr(ai.httpx, "post", reply)
    assert ai.generate("policy", [{"id": "pto", "text": "PTO"}])["mode"] == "OpenAI"
    monkeypatch.setattr(
        ai.httpx,
        "post",
        lambda *a, **k: (_ for _ in ()).throw(httpx.ConnectError("offline")),
    )
    assert ai.generate("policy", [{"id": "pto", "text": "PTO"}])["mode"] == "retrieval fallback"
