import pytest
from fastapi.testclient import TestClient

from app.llm import client as llm_client


@pytest.fixture(autouse=True)
def _fixture_packs(monkeypatch: pytest.MonkeyPatch):
    """Tests use tests/fixtures/knowledge (2 verified packs + 1 draft), not the real packs."""
    from pathlib import Path

    from app.config import Settings
    from app.research import packs

    monkeypatch.setattr(packs, "KNOWLEDGE", Path(__file__).parent / "fixtures" / "knowledge")
    # a local .env with PACKS_INCLUDE_DRAFT=true must not change what tests see
    monkeypatch.setattr(packs, "get_settings", lambda: Settings(_env_file=None))
    packs.all_packs.cache_clear()
    packs.portals.cache_clear()
    yield
    packs.all_packs.cache_clear()
    packs.portals.cache_clear()


@pytest.fixture(autouse=True)
def _no_paid_web_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    """Context.dev costs credits: off in every test, even with a key in a local .env. Its own
    tests turn it back on with a mocked transport."""
    from app.research import contextdev

    monkeypatch.setattr(contextdev, "enabled", lambda s: False)
    contextdev.breaker.success()


@pytest.fixture(autouse=True)
def _fresh_llm_state() -> None:
    """Module-level discovery cache and breakers must not leak between tests."""
    from app.research import search

    llm_client.reset_discovery()
    llm_client.breakers.update(gpu=llm_client.Breaker(), fallback=llm_client.Breaker())
    search.breaker.success()


class FakeStore:
    """In-memory stand-in for app.db.supabase: one user's rows, user scoping checked."""

    def __init__(self, user_id: str = "u1") -> None:
        self.user_id = user_id
        self.profile: dict = {"id": user_id}
        self.sources: dict[str, dict] = {}
        self.sessions: dict[str, dict] = {
            "s1": {"id": "s1", "user_id": user_id, "phase": "onboarding", "portal": None}
        }
        self.messages: list[dict] = []
        self.proposals: list[dict] = []
        self.audit: list[tuple[str, dict]] = []
        self.fetched: list[dict] = []
        self.research: list[dict] = []
        self.cache: list[dict] = []  # research_cache: shared, no user scoping

    def _own(self, user_id: str) -> bool:
        return user_id == self.user_id

    def get_profile(self, _db, user_id):
        return dict(self.profile) if self._own(user_id) else None

    def update_profile(self, _db, user_id, values, source_type, source_ref=None):
        assert self._own(user_id)
        self.profile.update(values)
        for k in values:
            self.sources[k] = {"source_type": source_type, "source_ref": source_ref or {}}
        return dict(self.profile)

    def get_assistant(self, _db, user_id):
        return {"assistant_name": "Aster", "avatar_id": "aster"} if self._own(user_id) else None

    def get_session(self, _db, user_id, session_id):
        s = self.sessions.get(session_id)
        return dict(s) if s and s["user_id"] == user_id else None

    def update_session(self, _db, user_id, session_id, values):
        s = self.sessions[session_id]
        assert s["user_id"] == user_id
        s.update(values)
        return dict(s)

    def add_message(self, _db, user_id, session_id, values):
        assert self._own(user_id)
        row = {"id": f"m{len(self.messages) + 1}", **values, "session_id": session_id}
        self.messages.append(row)
        return row

    def list_messages(self, _db, user_id, session_id, limit=50):
        assert self._own(user_id)
        return [m for m in self.messages if m["session_id"] == session_id][-limit:]

    def create_proposal(self, _db, user_id, values):
        row = {"id": f"p{len(self.proposals) + 1}", "user_id": user_id, "status": "pending"}
        self.proposals.append({**row, **values})
        return self.proposals[-1]

    def proposal_for_flag(self, _db, user_id, flag_id):
        return next(
            (
                p
                for p in self.proposals
                if p["user_id"] == user_id and (p.get("source_ref") or {}).get("flag_id") == flag_id
            ),
            None,
        )

    def get_pending_proposal(self, _db, user_id, proposal_id):
        return next(
            (
                p
                for p in self.proposals
                if p["id"] == proposal_id and p["user_id"] == user_id and p["status"] == "pending"
            ),
            None,
        )

    def latest_pending_proposal(self, _db, user_id, session_id):
        pend = [
            p
            for p in self.proposals
            if p["user_id"] == user_id
            and p["session_id"] == session_id
            and p["status"] == "pending"
        ]
        return pend[-1] if pend else None

    def set_proposal_status(self, _db, user_id, proposal_id, status):
        p = self.get_pending_proposal(_db, user_id, proposal_id)
        if p:
            p["status"] = status

    def write_audit(self, _db, user_id, session_id, action, payload, actor="system"):
        assert self._own(user_id)
        self.audit.append((action, payload))

    def add_fetched(self, _db, user_id, session_id, values):
        row = {
            "id": f"fc{len(self.fetched) + 1}",
            **values,
            "user_id": user_id,
            "session_id": session_id,
            "fetched_at": "2026-10-03T10:00:00+00:00",
        }
        self.fetched.append(row)
        return row

    def get_fetched(self, _db, user_id, session_id, content_id):
        return next(
            (
                f
                for f in self.fetched
                if f["id"] == content_id
                and f["user_id"] == user_id
                and f["session_id"] == session_id
            ),
            None,
        )

    def find_fetched(self, _db, user_id, session_id, url):
        rows = [
            f
            for f in self.fetched
            if f["url"] == url and f["user_id"] == user_id and f["session_id"] == session_id
        ]
        return rows[-1] if rows else None

    def list_fetched(self, _db, user_id, session_id):
        assert self._own(user_id)
        return [
            {"id": f["id"], "url": f["url"]} for f in self.fetched if f["session_id"] == session_id
        ]

    def fresh_research_cache(self, _db):
        from datetime import UTC, datetime

        now = datetime.now(UTC).isoformat()
        return [dict(r) for r in self.cache if r["expires_at"] > now]

    def put_research_cache(self, _db, values):
        self.cache = [r for r in self.cache if r["scheme_norm"] != values["scheme_norm"]]
        self.cache.append(dict(values))

    def add_research(self, _db, user_id, session_id, values):
        assert self._own(user_id)
        row = {"id": f"r{len(self.research) + 1}", **values, "session_id": session_id}
        self.research.append(row)
        return row

    def latest_research(self, _db, user_id, session_id, scheme, kind=None):
        assert self._own(user_id)
        rows = [
            r
            for r in self.research
            if r["session_id"] == session_id
            and r["scheme"] == scheme
            and (kind is None or r["kind"] == kind)
        ]
        return rows[-1] if rows else None


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> FakeStore:
    from app.db import supabase as repo

    st = FakeStore()
    for name in (
        "get_profile",
        "update_profile",
        "get_assistant",
        "get_session",
        "update_session",
        "add_message",
        "list_messages",
        "create_proposal",
        "get_pending_proposal",
        "latest_pending_proposal",
        "set_proposal_status",
        "proposal_for_flag",
        "write_audit",
        "add_fetched",
        "get_fetched",
        "find_fetched",
        "add_research",
        "latest_research",
        "list_fetched",
        "fresh_research_cache",
        "put_research_cache",
    ):
        monkeypatch.setattr(repo, name, getattr(st, name))
    return st


COMPLETE_PROFILE = {
    "full_name": "Aarav Patil",
    "dob": "2005-05-12",
    "gender": "Male",
    "district": "Pune",
    "category": "OBC",
    "annual_family_income": 148000,
    "ssc_year": 2021,
    "ssc_percentage": 88.2,
    "hsc_year": 2023,
    "hsc_percentage": 81.5,
    "current_course": "B.E. Computer",
    "current_year": 2,
}


@pytest.fixture
def run(store: FakeStore, monkeypatch: pytest.MonkeyPatch):
    """run(llm, **run_turn kwargs) -> every message the turn sent."""
    import asyncio

    from app.agent import orchestrator
    from app.config import Settings
    from tests.test_agent import ctx

    sent: list = []

    async def send(m) -> None:
        sent.append(m)

    def go(llm, c=None, **kw) -> list:
        monkeypatch.setattr(orchestrator, "chat_stream", llm)
        turn = orchestrator.run_turn(
            Settings(), c or ctx(store), send, assistant_name="Aster", **kw
        )
        asyncio.run(turn)
        return sent

    return go


@pytest.fixture
def client(store: FakeStore, monkeypatch: pytest.MonkeyPatch):
    from types import SimpleNamespace

    from app.agent import orchestrator
    from app.db.supabase import get_db
    from app.main import app
    from tests.test_agent import FakeLLM
    from tests.test_api import get_user

    app.dependency_overrides[get_db] = lambda: SimpleNamespace(
        auth=SimpleNamespace(get_user=get_user)
    )
    llm = FakeLLM()
    monkeypatch.setattr(orchestrator, "chat_stream", llm)
    try:
        yield TestClient(app), llm
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def sid(store: FakeStore) -> str:
    """FakeStore keys sessions by id; give s1 a UUID id for the path."""
    u = "00000000-0000-0000-0000-0000000000aa"
    store.sessions[u] = {**store.sessions.pop("s1"), "id": u}
    return u
