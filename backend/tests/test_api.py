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
        )
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
