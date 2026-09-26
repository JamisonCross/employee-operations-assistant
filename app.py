"""Employee self-service with server-enforced scope and explicit review states."""

import os
import secrets
import sqlite3
import time
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from ai import generate
from retrieval import HANDBOOK, retrieve
from routing import route_question

ROOT = Path(__file__).parent
PEOPLE = {
    "alex": {"name": "Alex Morgan", "role": "employee"},
    "jordan": {"name": "Jordan Lee", "role": "employee"},
    "sam": {"name": "Sam Rivera", "role": "reviewer"},
}


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Login(Strict):
    person: Literal["alex", "jordan", "sam"]


class Question(Strict):
    question: str = Field(min_length=3, max_length=1000)


class Leave(Strict):
    category: Literal["pto", "parental", "medical", "other"]
    start: date
    end: date
    key: str = Field(min_length=8, max_length=80, pattern=r"^[a-zA-Z0-9-]+$")


class Decision(Strict):
    decision: Literal["approve", "decline"]
    note: str = Field(min_length=3, max_length=300)


def create_app(db_path=None):
    path = Path(db_path or os.getenv("APP_DB", ROOT / "runtime" / "employees.sqlite"))
    path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def db():
        connection = sqlite3.connect(path, timeout=15)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS balances (person TEXT PRIMARY KEY, hours INTEGER NOT NULL CHECK(hours >= 0));
        CREATE TABLE IF NOT EXISTS requests (id INTEGER PRIMARY KEY, person TEXT NOT NULL, category TEXT NOT NULL, start TEXT NOT NULL, end TEXT NOT NULL, hours INTEGER NOT NULL, status TEXT NOT NULL, reason TEXT NOT NULL, created TEXT NOT NULL, request_key TEXT NOT NULL, payload TEXT NOT NULL, UNIQUE(person, request_key));
        CREATE TABLE IF NOT EXISTS audit (id INTEGER PRIMARY KEY, actor TEXT NOT NULL, request_id INTEGER, event TEXT NOT NULL, note TEXT NOT NULL, created TEXT NOT NULL);
        """)
        for who, hours in [("alex", 120), ("jordan", 64), ("sam", 96)]:
            c.execute("INSERT OR IGNORE INTO balances VALUES (?,?)", (who, hours))
    app = FastAPI(title="Cedar · Employee Operations", version="1.0.0")
    sessions = {}

    def identity(authorization: str = Header(default="")):
        token = authorization.removeprefix("Bearer ")
        session = sessions.get(token)
        if not session or session[1] < time.time():
            raise HTTPException(401, "Choose a demo identity to start a new session.")
        return session[0]

    def reviewer(who=Depends(identity)):
        if PEOPLE[who]["role"] != "reviewer":
            raise HTTPException(403, "People reviewer access required.")
        return who

    def balance(c, who):
        total = c.execute("SELECT hours FROM balances WHERE person=?", (who,)).fetchone()[0]
        reserved = c.execute(
            "SELECT COALESCE(SUM(hours),0) FROM requests WHERE person=? AND category='pto' AND status IN ('submitted','escalated')",
            (who,),
        ).fetchone()[0]
        return {"hours": total, "reserved": reserved, "available": total - reserved}

    def stamp():
        return datetime.now(timezone.utc).isoformat()

    def audit(c, who, request_id, event, note=""):
        c.execute(
            "INSERT INTO audit(actor,request_id,event,note,created) VALUES (?,?,?,?,?)",
            (who, request_id, event, note, stamp()),
        )

    @app.get("/")
    def index():
        return FileResponse(ROOT / "static" / "index.html")

    @app.get("/api/health")
    def health():
        return {"status": "ok", "synthetic": True}

    @app.post("/api/session")
    def login(body: Login):
        # Deliberately public role switcher for LOCAL synthetic demo only. Not authentication.
        for token, session in list(sessions.items()):
            if session[1] < time.time():
                del sessions[token]
        token = secrets.token_urlsafe(32)
        sessions[token] = (body.person, time.time() + 3600)
        return {"token": token, "person": body.person, **PEOPLE[body.person]}

    @app.get("/api/me")
    def me(who=Depends(identity)):
        with db() as c:
            return {
                "person": who,
                **PEOPLE[who],
                "balance": balance(c, who),
                "mode": "OpenAI + local retrieval"
                if os.getenv("OPENAI_API_KEY")
                else "Local retrieval · no LLM key",
            }

    @app.get("/api/handbook")
    def handbook(who=Depends(identity)):
        return HANDBOOK

    @app.post("/api/chat")
    def chat(body: Question, who=Depends(identity)):
        q = body.question.lower()
        route = route_question(q, who, PEOPLE)
        if route == "escalate":
            ticket = escalate(who)
            return {
                "answer": f"This needs a People specialist. Review ticket #{ticket['id']} is open for private follow-up. I cannot disclose another employee’s records or decide sensitive or ambiguous matters. Your question text was not stored in the ticket.",
                "mode": "policy control",
                "citations": [],
                "action": "escalate",
                "ticket_id": ticket["id"],
            }
        if route == "ledger":
            with db() as c:
                b = balance(c, who)
            return {
                "answer": f"Your PTO ledger has {b['hours']} hours, with {b['reserved']} reserved for pending requests. You have {b['available']} hours available ({b['available'] / 8:g} working days).",
                "mode": "HR ledger",
                "citations": [],
                "action": "request",
            }
        if route == "request":
            return {
                "answer": "Use the request form to choose a category, start date and end date. I will calculate weekdays and route the request. A person must review it before it is approved.",
                "mode": "workflow",
                "citations": ["pto"],
                "sources": [p for p in HANDBOOK if p["id"] == "pto"],
                "action": "request",
            }
        passages = [] if route == "unsupported" else retrieve(q)
        if not passages:
            ticket = escalate(who)
            return {
                "answer": f"I could not find reliable support in the handbook. Review ticket #{ticket['id']} is open for a People specialist. Your question text was not stored in the ticket.",
                "mode": "no supporting source",
                "citations": [],
                "action": "escalate",
            }
        answer = generate(body.question, passages)
        return {
            **answer,
            "action": None,
            "sources": [p for p in passages if p["id"] in answer["citations"]],
        }

    @app.post("/api/escalations", status_code=201)
    def escalate(who=Depends(identity)):
        with db() as c:
            c.execute("BEGIN IMMEDIATE")
            # One open generic ticket per person; no free-text sensitive data collected.
            old = c.execute(
                "SELECT * FROM requests WHERE person=? AND category='people' AND status='escalated'",
                (who,),
            ).fetchone()
            if old:
                return dict(old)
            cur = c.execute(
                "INSERT INTO requests(person,category,start,end,hours,status,reason,created,request_key,payload) VALUES (?,'people','','',0,'escalated','Private follow-up requested',?,?, '{}')",
                (who, stamp(), secrets.token_hex(16)),
            )
            audit(c, who, cur.lastrowid, "escalated")
            return dict(c.execute("SELECT * FROM requests WHERE id=?", (cur.lastrowid,)).fetchone())

    @app.post("/api/requests", status_code=201)
    def request(body: Leave, who=Depends(identity)):
        payload = body.model_dump_json(exclude={"key"})
        with db() as c:
            c.execute("BEGIN IMMEDIATE")
            previous = c.execute(
                "SELECT * FROM requests WHERE person=? AND request_key=?",
                (who, body.key),
            ).fetchone()
            if previous:
                if previous["payload"] != payload:
                    raise HTTPException(
                        409, "This request key was already used for different details."
                    )
                return dict(previous)
            if (
                body.start < date.today()
                or body.end < body.start
                or (body.end - body.start).days > 365
            ):
                raise HTTPException(422, "Use future dates in order, at most one year apart.")
            hours = (
                sum(
                    (body.start + timedelta(days=i)).weekday() < 5
                    for i in range((body.end - body.start).days + 1)
                )
                * 8
            )
            if not hours:
                raise HTTPException(422, "Choose a range containing at least one weekday.")
            overlap = c.execute(
                "SELECT id FROM requests WHERE person=? AND category!='people' AND status IN ('submitted','escalated','approved') AND start<=? AND end>=?",
                (who, body.end.isoformat(), body.start.isoformat()),
            ).fetchone()
            if overlap:
                raise HTTPException(409, "These dates overlap an active request.")
            b = balance(c, who)
            reasons = []
            if body.category != "pto":
                reasons.append("People must determine eligibility and next steps")
            if hours > 40:
                reasons.append("More than five working days")
            if body.category == "pto" and hours > b["available"]:
                reasons.append("Insufficient available PTO; human decision required")
            # Insufficient-balance requests do not reserve unusable hours.
            recorded_hours = hours if body.category == "pto" and hours <= b["available"] else 0
            status = "escalated" if reasons else "submitted"
            cur = c.execute(
                "INSERT INTO requests(person,category,start,end,hours,status,reason,created,request_key,payload) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    who,
                    body.category,
                    body.start.isoformat(),
                    body.end.isoformat(),
                    recorded_hours,
                    status,
                    "; ".join(reasons) or "Submitted to mock HR; awaiting People approval",
                    stamp(),
                    body.key,
                    payload,
                ),
            )
            audit(c, who, cur.lastrowid, status)
            return dict(c.execute("SELECT * FROM requests WHERE id=?", (cur.lastrowid,)).fetchone())

    @app.get("/api/requests")
    def requests(who=Depends(identity)):
        with db() as c:
            return [
                dict(r)
                for r in c.execute("SELECT * FROM requests WHERE person=? ORDER BY id DESC", (who,))
            ]

    @app.get("/api/review")
    def review(who=Depends(reviewer)):
        with db() as c:
            return {
                "requests": [dict(r) for r in c.execute("SELECT * FROM requests ORDER BY id DESC")],
                "audit": [
                    dict(r) for r in c.execute("SELECT * FROM audit ORDER BY id DESC LIMIT 100")
                ],
            }

    @app.post("/api/review/{request_id}")
    def decide(request_id: int, body: Decision, who=Depends(reviewer)):
        with db() as c:
            c.execute("BEGIN IMMEDIATE")
            r = c.execute("SELECT * FROM requests WHERE id=?", (request_id,)).fetchone()
            if not r:
                raise HTTPException(404, "Request not found.")
            if r["person"] == who:
                raise HTTPException(403, "A reviewer cannot decide their own request.")
            if r["status"] not in ("submitted", "escalated"):
                raise HTTPException(409, "This request has already been decided.")
            if body.decision == "approve" and r["category"] == "pto":
                if not r["hours"]:
                    raise HTTPException(
                        409,
                        "Insufficient-balance request cannot be approved; decline and discuss alternatives.",
                    )
                updated = c.execute(
                    "UPDATE balances SET hours=hours-? WHERE person=? AND hours>=?",
                    (r["hours"], r["person"], r["hours"]),
                )
                if updated.rowcount != 1:
                    raise HTTPException(409, "PTO balance changed; review the ledger.")
            status = "approved" if body.decision == "approve" else "declined"
            # For non-PTO cases, approval means a HUMAN has acknowledged follow-up, not leave eligibility.
            if body.decision == "approve" and r["category"] != "pto":
                status = "human_followup"
            c.execute("UPDATE requests SET status=? WHERE id=?", (status, request_id))
            audit(c, who, request_id, status, body.note)
            return {"id": request_id, "status": status}

    app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
    return app


app = create_app()
