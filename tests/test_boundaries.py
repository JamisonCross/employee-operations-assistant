import json
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from fastapi.testclient import TestClient

import ai
from app import create_app, retrieve


@pytest.mark.parametrize(
    "question,expected",
    [
        ("What is the parental leave policy?", "parental"),
        ("What should I do for onboarding?", "onboarding"),
        ("Who helps with remote equipment?", "remote"),
        ("What is the price of bitcoin?", None),
    ],
)
def test_retrieval_relevance(question, expected):
    passages = retrieve(question)
    if expected:
        assert passages[0]["id"] == expected
    else:
        assert passages == []
    if expected == "parental":
        assert "onboarding" not in [p["id"] for p in passages]


def test_automatic_escalation_is_private_and_concurrency_safe(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    c = TestClient(create_app(tmp_path / "test.sqlite"))
    token = c.post("/api/session", json={"person": "alex"}).json()["token"]
    headers = {"Authorization": "Bearer " + token}

    def question():
        return c.post(
            "/api/chat",
            headers=headers,
            json={"question": "I am not sure whether I can take unpaid leave."},
        ).json()

    with ThreadPoolExecutor(2) as pool:
        answers = list(pool.map(lambda _: question(), range(2)))
    assert answers[0]["ticket_id"] == answers[1]["ticket_id"]
    records = c.get("/api/requests", headers=headers).json()
    assert len(records) == 1 and records[0]["status"] == "escalated"
    assert "unpaid" not in json.dumps(records)


@pytest.mark.parametrize(
    "result",
    [
        {"status": "incomplete", "output": []},
        {
            "status": "completed",
            "output": [{"content": [{"type": "refusal", "refusal": "Cannot answer"}]}],
        },
        {
            "status": "completed",
            "output": [
                {
                    "content": [
                        {
                            "type": "output_text",
                            "text": '{"answer":"Invented", "citations":["missing-source"]}',
                        }
                    ]
                }
            ],
        },
        {"status": "completed", "output": ["invalid provider shape"]},
    ],
)
def test_provider_failure_modes_do_not_escape_boundary(monkeypatch, result):
    monkeypatch.setenv("OPENAI_API_KEY", "test-only")
    monkeypatch.setattr(
        ai.httpx,
        "post",
        lambda url, **kw: httpx.Response(200, request=httpx.Request("POST", url), json=result),
    )
    response = ai.generate("Policy question", [{"id": "pto", "text": "Approved source text."}])
    assert response["mode"] == "retrieval fallback"
    assert response["citations"] == ["pto"]
