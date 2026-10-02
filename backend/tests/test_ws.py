import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.agent import orchestrator
from app.db.supabase import get_db
from app.main import app
from tests.conftest import COMPLETE_PROFILE, FakeStore
from tests.test_agent import FakeLLM, text
from tests.test_api import get_user

HELLO = {"type": "hello", "token": "good", "lang": "mr"}


@pytest.fixture
def client(store: FakeStore, monkeypatch: pytest.MonkeyPatch):
    from types import SimpleNamespace

    app.dependency_overrides[get_db] = lambda: SimpleNamespace(
        auth=SimpleNamespace(get_user=get_user)
    )
    llm = FakeLLM()
    monkeypatch.setattr(orchestrator, "chat_stream", llm)
    try:
        yield TestClient(app), llm
    finally:
        app.dependency_overrides.clear()


def until(ws, type_: str) -> list[dict]:
    got = []
    while not got or got[-1]["type"] != type_:
        got.append(ws.receive_json())
    return got


@pytest.mark.parametrize(
    "path,first,code",
    [
        ("/ws/session/00000000-0000-0000-0000-000000000001", {"type": "ping"}, 4400),
        ("/ws/session/00000000-0000-0000-0000-000000000001", {**HELLO, "token": "bad"}, 4401),
        # a valid user, but not their session (FakeStore only has s1 for u1)
        ("/ws/session/00000000-0000-0000-0000-000000000002", HELLO, 4404),
    ],
)
def test_rejects(client, path: str, first: dict, code: int) -> None:
    c, _ = client
    with c.websocket_connect(path) as ws:
        ws.send_json(first)
        assert ws.receive_json()["type"] == "error"
        with pytest.raises(WebSocketDisconnect) as e:
            ws.receive_json()
        assert e.value.code == code


@pytest.fixture
def sid(store: FakeStore) -> str:
    """FakeStore keys sessions by id; give s1 a UUID id for the path."""
    u = "00000000-0000-0000-0000-0000000000aa"
    store.sessions[u] = {**store.sessions.pop("s1"), "id": u}
    return u


def test_conversation(client, store: FakeStore, sid: str) -> None:
    c, llm = client
    llm.rounds += [text("नमस्कार! तुमचं नाव काय?"), text("छान, आरव!")]
    with c.websocket_connect(f"/ws/session/{sid}") as ws:
        ws.send_json(HELLO)
        ready = ws.receive_json()
        assert ready == {
            "type": "ready",
            "phase": "onboarding",
            "assistant": {"name": "Aster", "avatar_id": "aster"},
        }
        greet = until(ws, "assistant_message")  # new session: Aster speaks first
        assert greet[-1]["text"] == "नमस्कार! तुमचं नाव काय?"
        assert "Conversation started" in llm.calls[0]["messages"][-1]["content"]
        assert until(ws, "agent_state")[-1]["state"] == "idle"
        ws.send_json({"type": "user_text", "text": "आरव"})
        got = until(ws, "assistant_message")
        assert [m for m in got if m["type"] == "assistant_delta"][0]["text"] == "छान, आरव!"
        assert got[-1]["lang"] == "mr"
        ws.send_json({"type": "ping"})
        assert until(ws, "pong")[-1] == {"type": "pong"}
        ws.send_json({"type": "audio_start"})
        assert ws.receive_json()["code"] == "bad_message"
    assert [m["role"] for m in store.messages] == ["system", "assistant", "user", "assistant"]


def test_form_selected_card_tap(client, store: FakeStore, sid: str) -> None:
    c, llm = client
    store.profile.update(COMPLETE_PROFILE)
    store.messages.append({"id": "m0", "session_id": sid, "role": "user", "content": "hi"})
    llm.rounds += [text("MahaDBT निवडले!")]
    with c.websocket_connect(f"/ws/session/{sid}") as ws:
        ws.send_json(HELLO)
        assert [m["type"] for m in until(ws, "ready")] == ["phase", "ready"]  # -> choose_form
        ws.send_json(
            {"type": "ui_event", "name": "form_selected", "payload": {"portal": "mahadbt"}}
        )
        got = until(ws, "assistant_message")
    assert {"type": "phase", "phase": "research"} in got
    assert store.sessions[sid]["portal"] == "mahadbt"
    assert "[UI event] The user picked mahadbt" in llm.calls[0]["messages"][-1]["content"]
    assert llm.calls[0]["tools"] is None  # the tap set the form in code, not via the LLM


def test_rate_limit(client, store: FakeStore, sid: str) -> None:
    c, _ = client
    store.messages.append({"id": "m0", "session_id": sid, "role": "user", "content": "hi"})
    with c.websocket_connect(f"/ws/session/{sid}") as ws:
        ws.send_json(HELLO)
        until(ws, "ready")
        for _ in range(30):
            ws.send_json({"type": "ping"})
            assert ws.receive_json()["type"] == "pong"
        ws.send_json({"type": "ping"})
        assert ws.receive_json()["code"] == "rate_limited"
