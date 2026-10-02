from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from supabase_auth.errors import AuthApiError

from app.db import supabase as repo
from app.db.supabase import get_db
from app.main import app

AUTH = {"Authorization": "Bearer good"}


def get_user(token: str) -> SimpleNamespace:
    if token != "good":
        raise AuthApiError("invalid JWT", 401, "bad_jwt")
    return SimpleNamespace(user=SimpleNamespace(id="u1"))


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch):
    """TestClient with a fake Supabase: auth stubbed, repo calls recorded."""
    calls: list[tuple[str, tuple]] = []

    def rec(name: str, result: Any):
        def f(*a: Any, **_kw: Any) -> Any:
            calls.append((name, a[1:]))  # drop db
            return result

        return f

    monkeypatch.setattr(repo, "get_profile", rec("get_profile", {"id": "u1"}))
    monkeypatch.setattr(repo, "get_assistant", rec("get_assistant", {"user_id": "u1"}))
    monkeypatch.setattr(repo, "upsert_assistant", rec("upsert_assistant", {"user_id": "u1"}))
    monkeypatch.setattr(repo, "update_profile", rec("update_profile", {"id": "u1"}))
    monkeypatch.setattr(repo, "create_session", rec("create_session", {"id": "s1"}))
    app.dependency_overrides[get_db] = lambda: SimpleNamespace(
        auth=SimpleNamespace(get_user=get_user)
    )
    try:
        yield TestClient(app), calls
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/api/me"),
        ("put", "/api/assistant"),
        ("put", "/api/profile"),
        ("post", "/api/sessions"),
    ],
)
@pytest.mark.parametrize(
    "headers", [{}, {"Authorization": "Bearer bad"}, {"Authorization": "good"}]
)
def test_requires_valid_jwt(api, method: str, path: str, headers: dict) -> None:
    c, calls = api
    assert getattr(c, method)(path, headers=headers).status_code == 401
    assert calls == []


def test_me_scoped_to_jwt_user(api) -> None:
    c, calls = api
    r = c.get("/api/me", headers=AUTH)
    assert r.status_code == 200
    assert r.json() == {"profile": {"id": "u1"}, "assistant": {"user_id": "u1"}}
    assert calls == [("get_profile", ("u1",)), ("get_assistant", ("u1",))]


def test_put_assistant(api) -> None:
    c, calls = api
    body = {"avatar_id": "tara", "assistant_name": " Tara ", "language": "mr"}
    assert c.put("/api/assistant", json=body, headers=AUTH).status_code == 200
    assert calls == [
        ("upsert_assistant", ("u1", {**body, "assistant_name": "Tara", "voice": None}))
    ]
    for bad in [{**body, "avatar_id": "x"}, {**body, "language": "fr"}, {**body, "user_id": "u2"}]:
        assert c.put("/api/assistant", json=bad, headers=AUTH).status_code == 422


def test_put_profile_casts_and_drops_blanks(api) -> None:
    c, calls = api
    body = {
        "full_name": "Asha Patil",
        "ssc_year": "2022",
        "hsc_percentage": "81.5",
        "dob": "2006-04-01",
        "district": "",
        "aadhaar_last4": "1234",
    }
    assert c.put("/api/profile", json=body, headers=AUTH).status_code == 200
    assert calls == [
        ("get_profile", ("u1",)),
        (
            "update_profile",
            (
                "u1",
                {
                    "full_name": "Asha Patil",
                    "dob": "2006-04-01",
                    "ssc_year": 2022,
                    "hsc_percentage": 81.5,
                    "aadhaar_last4": "1234",
                },
            ),
        ),
    ]


@pytest.mark.parametrize(
    "bad",
    [
        {"aadhaar_last4": "123456789012"},  # full Aadhaar never accepted (guardrail 6)
        {"bank_account": "123"},  # unknown keys rejected
        {"id": "u2"},  # cannot target another user
        {"ssc_percentage": "140"},
    ],
)
def test_put_profile_rejects(api, bad: dict) -> None:
    c, calls = api
    assert c.put("/api/profile", json=bad, headers=AUTH).status_code == 422
    assert calls == []


def test_create_session(api) -> None:
    c, calls = api
    body = {"portal": "mahadbt", "portal_url": "https://mahadbt.maharashtra.gov.in"}
    r = c.post("/api/sessions", json=body, headers=AUTH)
    assert r.status_code == 201 and r.json() == {"id": "s1"}
    assert calls == [
        (
            "create_session",
            ("u1", {"portal": "mahadbt", "portal_url": "https://mahadbt.maharashtra.gov.in/"}),
        )
    ]
    assert c.post("/api/sessions", json={"user_id": "u2"}, headers=AUTH).status_code == 422
    assert (
        c.post("/api/sessions", json={"portal_url": "javascript:x"}, headers=AUTH).status_code
        == 422
    )


# ---------- POST /api/profile/confirm (guardrail 4) ----------
P1 = "00000000-0000-0000-0000-0000000000a1"


@pytest.fixture
def confirm(store, monkeypatch: pytest.MonkeyPatch):
    from types import SimpleNamespace

    store.proposals.append(
        {
            "id": P1,
            "user_id": "u1",
            "session_id": "s1",
            "status": "pending",
            "evidence": "text",
            "message_id": "m1",
            "updates": {"full_name": "Aarav Patil", "district": "Pune", "ssc_year": 2021},
        }
    )
    app.dependency_overrides[get_db] = lambda: SimpleNamespace(
        auth=SimpleNamespace(get_user=get_user)
    )
    try:
        yield lambda body: TestClient(app).post("/api/profile/confirm", json=body, headers=AUTH)
    finally:
        app.dependency_overrides.clear()


def test_confirm_saves_with_sources(confirm, store) -> None:
    r = confirm({"proposal_id": P1, "accept": True, "edits": {"district": "Pune City"}})
    assert r.status_code == 200
    assert store.profile == {
        "id": "u1",
        "full_name": "Aarav Patil",
        "district": "Pune City",
        "ssc_year": 2021,
    }
    ref = {"proposal_id": P1, "message_id": "m1"}
    assert store.sources == {
        "full_name": {"source_type": "text", "source_ref": ref},
        "ssc_year": {"source_type": "text", "source_ref": ref},
        "district": {"source_type": "manual", "source_ref": ref},  # corrected in the card
    }
    assert store.proposals[0]["status"] == "accepted"
    action, payload = store.audit[-1]
    assert action == "profile.confirmed" and "Pune" not in str(payload)  # names only, no values
    # answered once: a second confirm finds nothing pending
    assert confirm({"proposal_id": P1, "accept": True}).status_code == 404


def test_confirm_blank_edit_skips_field(confirm, store) -> None:
    assert (
        confirm({"proposal_id": P1, "accept": True, "edits": {"district": ""}}).status_code == 200
    )
    assert "district" not in store.profile and "district" not in store.sources


def test_reject_saves_nothing(confirm, store) -> None:
    assert confirm({"proposal_id": P1, "accept": False}).json()["status"] == "rejected"
    assert store.profile == {"id": "u1"} and store.audit[-1][0] == "profile.rejected"


@pytest.mark.parametrize(
    "body,code",
    [
        ({"proposal_id": P1, "accept": True, "edits": {"caste": "X"}}, 422),  # not proposed
        ({"proposal_id": P1, "accept": True, "edits": {"ssc_year": "1800"}}, 422),
        ({"proposal_id": "00000000-0000-0000-0000-000000000009", "accept": True}, 404),
        ({"proposal_id": P1, "accept": True, "user_id": "u2"}, 422),
    ],
)
def test_confirm_rejects(confirm, store, body: dict, code: int) -> None:
    assert confirm(body).status_code == code
    assert store.profile == {"id": "u1"} and store.proposals[0]["status"] == "pending"


def test_confirm_other_users_proposal(confirm, store) -> None:
    store.proposals[0]["user_id"] = "u2"
    assert confirm({"proposal_id": P1, "accept": True}).status_code == 404
    assert store.profile == {"id": "u1"}


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("आधार 1234 5678 9012 आहे", "आधार [number ending 9012] आहे"),
        ("aadhaar 123456789012", "aadhaar [number ending 9012]"),
        ("खाते ३१२३४५६७८९०१२३", "खाते [number ending ०१२३]"),
        ("acct 12345678901", "acct [number ending 8901]"),
        # kept: mobile, income, years, percentages
        ("9876543210, income 148000, 2021, 81.5%", "9876543210, income 148000, 2021, 81.5%"),
    ],
)
def test_redact_ids(raw: str, expected: str) -> None:
    assert repo.redact_ids(raw) == expected


def test_add_message_redacts_before_storing() -> None:
    inserted: list[dict] = []

    class Q:
        def insert(self, row):
            inserted.append(row)
            return self

        def execute(self):
            return SimpleNamespace(data=[inserted[-1]])

    db = SimpleNamespace(table=lambda _name: Q())
    repo.add_message(
        db,
        "u1",
        "s1",
        {"role": "tool", "content": "1234-5678-9012", "tool_payload": {"args": "123456789012"}},
    )
    assert inserted[0]["content"] == "[number ending 9012]"
    assert inserted[0]["tool_payload"] == {"args": "[number ending 9012]"}


def test_put_profile_skips_unchanged_fields(api, monkeypatch: pytest.MonkeyPatch) -> None:
    c, calls = api
    monkeypatch.setattr(repo, "get_profile", lambda *_a: {"id": "u1", "full_name": "Asha Patil"})
    body = {"full_name": "Asha Patil", "district": "Pune"}
    assert c.put("/api/profile", json=body, headers=AUTH).status_code == 200
    assert calls == [("update_profile", ("u1", {"district": "Pune"}))]
