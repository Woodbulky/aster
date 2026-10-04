import pytest
from starlette.websockets import WebSocketDisconnect

from tests.conftest import COMPLETE_PROFILE, FakeStore
from tests.test_agent import text

HELLO = {"type": "hello", "token": "good", "lang": "mr"}


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
    llm.rounds += [text("४ पैकी २ अटी जुळतात असे दिसते.")]
    with c.websocket_connect(f"/ws/session/{sid}") as ws:
        ws.send_json(HELLO)
        assert [m["type"] for m in until(ws, "ready")] == ["phase", "ready"]  # -> choose_form
        ws.send_json(
            {
                "type": "ui_event",
                "name": "form_selected",
                "payload": {"portal": "demo", "scheme_key": "demo.obc_aid"},
            }
        )
        got = until(ws, "assistant_message")
    # set_form -> pack research -> eligibility card, all in code before the LLM speaks
    assert [m["phase"] for m in got if m["type"] == "phase"] == ["research", "eligibility"]
    tools = [(m["name"], m["status"]) for m in got if m["type"] == "tool_event"]
    assert tools == [
        (n, s)
        for n in ("set_form", "get_knowledge_pack", "check_eligibility")
        for s in ("started", "done")
    ]
    card = next(m for m in got if m["type"] == "card")
    assert card["kind"] == "eligibility"
    statuses = {r["id"]: r["status"] for r in card["payload"]["results"]}
    assert statuses == {
        "obc": "met",
        "income": "met",
        "domicile": "unknown",
        "attendance": "unknown",
    }
    assert store.sessions[sid]["scheme_key"] == "demo.obc_aid"
    assert {(r["kind"], r["origin"]) for r in store.research} == {
        ("eligibility", "pack"),
        ("documents", "pack"),
    }
    # the card is stored with its tool row, so a reload can show it again
    assert any(m.get("tool_name") == "check_eligibility" for m in store.messages)
    prompt = llm.calls[0]["messages"][-1]["content"]
    assert "[UI event] The user picked OBC Aid" in prompt and "domicile_state" in prompt
    assert "Current phase: eligibility" in llm.calls[0]["messages"][0]["content"]


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


def test_set_lang_switches_replies_on_the_open_socket(client, store: FakeStore, sid: str) -> None:
    c, llm = client
    llm.rounds += [text("नमस्कार!"), text("नमस्ते!")]
    with c.websocket_connect(f"/ws/session/{sid}") as ws:
        ws.send_json(HELLO)
        until(ws, "assistant_message")  # greeting, in Marathi
        until(ws, "agent_state")
        ws.send_json({"type": "set_lang", "lang": "hi"})
        ws.send_json({"type": "user_text", "text": "hello"})
        assert until(ws, "assistant_message")[-1]["lang"] == "hi"  # no reconnect needed
        assert "Hindi" in llm.calls[-1]["messages"][0]["content"]


def test_set_lang_mid_turn_waits_for_that_reply(
    client, store: FakeStore, sid: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Guardrail 9: a reply written in Marathi is stored as Marathi even if the toggle moved."""
    import asyncio

    from app.agent import orchestrator
    from app.llm.client import Chunk

    c, _ = client

    async def slow(_s, _msgs, **_kw):
        await asyncio.sleep(0.3)
        yield Chunk("fallback", {"content": "नमस्कार!"})

    monkeypatch.setattr(orchestrator, "chat_stream", slow)
    with c.websocket_connect(f"/ws/session/{sid}") as ws:
        ws.send_json(HELLO)  # the greeting turn starts, in Marathi
        ws.send_json({"type": "set_lang", "lang": "hi"})
        assert until(ws, "assistant_message")[-1]["lang"] == "mr"
        ws.send_json({"type": "user_text", "text": "hello"})
        assert until(ws, "assistant_message")[-1]["lang"] == "hi"
    assert [m["lang"] for m in store.messages if m["role"] == "assistant"] == ["mr", "hi"]


def test_a_batch_of_documents_gets_one_spoken_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cards at once for each document; the spoken summary waits for the last one of the batch."""
    import asyncio
    from datetime import UTC, datetime, timedelta
    from types import SimpleNamespace

    from app.agent.tools import ToolResult
    from app.ws import voice

    now = datetime.now(UTC).isoformat()
    docs = {
        "00000000-0000-0000-0000-00000000000a": "processing",
        "00000000-0000-0000-0000-00000000000b": "processing",
        # cut off by a restart long ago: never waited for
        "00000000-0000-0000-0000-00000000000c": "processing",
    }
    old = (datetime.now(UTC) - timedelta(minutes=10)).isoformat()
    cards: list[str] = []
    turns: list[str] = []

    async def tool(_ctx, _send, name, args):
        cards.append(args["document_id"])
        return ToolResult(ok=True, data={"document": args["document_id"][-1], "status": "read"})

    async def no_flags(_ctx, _send):
        return []

    async def turn(**kw):
        turns.append(kw["ui_event"])

    def listed(_db, _u, _s):
        return [
            {"id": k, "status": v, "created_at": old if k.endswith("c") else now}
            for k, v in docs.items()
        ]

    monkeypatch.setattr(voice, "run_tool_ui", tool)
    monkeypatch.setattr(voice, "show_new_flag_cards", no_flags)
    monkeypatch.setattr(voice.repo, "list_documents", listed)
    ctx = SimpleNamespace(db=None, user_id="u1", session={"id": "s1"})
    batch: list = []

    async def done(doc_id: str) -> None:
        docs[doc_id] = "extracted"
        await voice._document_processed(ctx, None, {"document_id": doc_id}, turn, batch)

    asyncio.run(done("00000000-0000-0000-0000-00000000000a"))
    assert cards == ["00000000-0000-0000-0000-00000000000a"] and turns == []  # b still reading
    asyncio.run(done("00000000-0000-0000-0000-00000000000b"))
    assert len(cards) == 2 and len(turns) == 1  # one summary for both
    assert '"document": "a"' in turns[0] and '"document": "b"' in turns[0]
    assert batch == []
