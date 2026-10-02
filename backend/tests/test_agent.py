import asyncio
import json
from types import SimpleNamespace
from typing import Any

import pytest

from app.agent import orchestrator
from app.agent.tools import Ctx, run_tool
from app.config import Settings
from app.llm.client import Chunk, LLMUnavailable
from tests.conftest import COMPLETE_PROFILE, FakeStore


def ctx(store: FakeStore, lang: str = "mr") -> Ctx:
    return Ctx(db=SimpleNamespace(), user_id="u1", session=store.sessions["s1"], lang=lang)


def call(name: str, args: dict, i: int = 0) -> list[Chunk]:
    tc = {"index": i, "id": f"c{i}", "function": {"name": name, "arguments": json.dumps(args)}}
    return [Chunk("fallback", {"tool_calls": [tc]}), Chunk("fallback", {}, "tool_calls")]


def text(t: str) -> list[Chunk]:
    return [Chunk("fallback", {"content": t}), Chunk("fallback", {}, "stop")]


class FakeLLM:
    """Plays scripted completions; records what each call received."""

    def __init__(self, *rounds: list[Chunk] | Exception) -> None:
        self.rounds = list(rounds)
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, _s, messages, *, tools=None, **_kw):
        self.calls.append({"messages": [dict(m) for m in messages], "tools": tools})
        r = self.rounds.pop(0)
        if isinstance(r, Exception):
            raise r
        for ch in r:
            yield ch


@pytest.fixture
def run(store: FakeStore, monkeypatch: pytest.MonkeyPatch):
    sent: list[Any] = []

    async def send(m) -> None:
        sent.append(m)

    def go(llm: FakeLLM, c: Ctx | None = None, **kw) -> list[Any]:
        monkeypatch.setattr(orchestrator, "chat_stream", llm)
        turn = orchestrator.run_turn(
            Settings(), c or ctx(store), send, assistant_name="Aster", **kw
        )
        asyncio.run(turn)
        return sent

    return go


def kinds(sent: list[Any]) -> list[str]:
    return [m.type for m in sent]


# ---------- tools ----------
def test_get_profile_masks_sensitive(store: FakeStore) -> None:
    store.profile.update(full_name="Aarav", caste="Maratha", aadhaar_last4="1234", email="a@b.c")
    res = run_tool(ctx(store), "get_profile", "{}")
    assert res.data["profile"] == {
        "full_name": "Aarav",
        "caste": "provided",
        "aadhaar_last4": "provided",
    }
    assert "district" in res.data["missing_core"]


def test_propose_creates_card_but_saves_nothing(store: FakeStore) -> None:
    c = ctx(store)
    c.message_id = "m9"
    args = {"updates": {"full_name": "Aarav Patil", "ssc_year": "2021", "gender": "Male"}}
    res = run_tool(c, "propose_profile_update", args)
    assert res.ok and res.card and res.card.kind == "confirm_profile"
    assert res.card.payload["updates"] == {
        "full_name": "Aarav Patil",
        "gender": "Male",
        "ssc_year": 2021,
    }
    assert store.proposals[0]["message_id"] == "m9" and store.proposals[0]["evidence"] == "text"
    assert store.profile == {"id": "u1"} and store.sources == {}  # guardrail 4


@pytest.mark.parametrize(
    "updates",
    [
        {"date_of_birth": "2005-05-12"},  # unknown key
        {"aadhaar_last4": "123456789012"},  # full Aadhaar (guardrail 6)
        {"aadhaar_number": "123456789012"},
        {"gender": "M"},  # not a form option
        {"dob": "12/05/2005"},
        {},
    ],
)
def test_propose_rejects(store: FakeStore, updates: dict) -> None:
    res = run_tool(ctx(store), "propose_profile_update", {"updates": updates})
    assert not res.ok and res.error
    assert store.proposals == []


def test_tool_not_in_phase_is_refused(store: FakeStore) -> None:
    res = run_tool(ctx(store), "set_form", {"portal": "mahadbt"})  # session is in onboarding
    assert not res.ok and "not available" in res.error
    assert store.sessions["s1"]["portal"] is None


def test_bad_json_args(store: FakeStore) -> None:
    assert run_tool(ctx(store), "get_profile", "{not json").error == "arguments are not valid JSON"


def test_explain_why_asked_uses_template(store: FakeStore) -> None:
    res = run_tool(ctx(store, "mr"), "explain_why_asked", {"field_key": "annual_family_income"})
    assert "उत्पन्न" in res.data["text"] and res.data["source"]
    res = run_tool(ctx(store, "en"), "explain_why_asked", {"field_key": "pet_name"})
    assert res.data["text"].startswith("I ask so")


def test_set_form(store: FakeStore) -> None:
    store.sessions["s1"]["phase"] = "choose_form"
    assert not run_tool(ctx(store), "set_form", {"portal": "nsp"}).ok
    res = run_tool(ctx(store), "set_form", {"portal": "MahaDBT", "portal_url": "https://evil.x"})
    assert not res.ok  # extra args forbidden: the portal URL is never LLM-supplied
    res = run_tool(ctx(store), "set_form", {"portal": "Maha DBT"})
    assert res.ok
    assert store.sessions["s1"]["portal"] == "mahadbt"
    assert store.sessions["s1"]["portal_url"] == "https://mahadbt.maharashtra.gov.in"
    assert store.audit[-1][0] == "form.set"


def test_suggest_schemes_stub(store: FakeStore) -> None:
    store.sessions["s1"]["phase"] = "choose_form"
    res = run_tool(ctx(store), "suggest_schemes", {"portal": "mahadbt"})
    assert res.card.kind == "scheme_suggestions"
    assert res.card.payload["options"][0]["portal"] == "mahadbt"


# ---------- orchestrator ----------
def test_onboarding_turn(store: FakeStore, run) -> None:
    llm = FakeLLM(
        call(
            "propose_profile_update", {"updates": {"full_name": "Aarav Patil", "district": "Pune"}}
        ),
        text("कृपया कार्ड तपासा."),
    )
    sent = run(llm, user_text="माझं नाव आरव पाटील, पुण्यात राहतो.")
    assert store.messages[0] | {"id": "m1"} == {
        "id": "m1",
        "role": "user",
        "content": "माझं नाव आरव पाटील, पुण्यात राहतो.",
        "lang": "mr",
        "input_mode": "text",
        "session_id": "s1",
    }
    assert store.proposals[0]["message_id"] == "m1"  # evidence = the user's message
    assert store.profile == {"id": "u1"}  # nothing saved before the card is confirmed
    k = kinds(sent)
    assert k[0] == "agent_state" and "card" in k and k[-2:] == ["assistant_message", "agent_state"]
    assert [m.status for m in sent if m.type == "tool_event"] == ["started", "done"]
    final = sent[-2]
    assert final.text == "कृपया कार्ड तपासा." and final.lang == "mr"
    assert (
        store.messages[-1]["role"] == "assistant" and store.messages[-1]["id"] == final.message_id
    )
    # onboarding tools only; the prompt has the next question; the tool result went back
    first = llm.calls[0]
    assert {t["function"]["name"] for t in first["tools"]} == {
        "get_profile",
        "propose_profile_update",
        "explain_why_asked",
    }
    assert "तुमचं पूर्ण नाव" in first["messages"][0]["content"]
    assert llm.calls[1]["messages"][-1]["role"] == "tool"


def test_choose_form_to_research(store: FakeStore, run) -> None:
    store.profile.update(COMPLETE_PROFILE)
    llm = FakeLLM(call("set_form", {"portal": "mahadbt"}), text("ठीक आहे!"))
    sent = run(llm, user_text="MahaDBT")
    # onboarding -> choose_form at the start of the turn, -> research after set_form
    assert [m.phase for m in sent if m.type == "phase"] == ["choose_form", "research"]
    assert store.sessions["s1"]["phase"] == "research"
    assert [a for a, _ in store.audit] == ["phase.changed", "form.set", "phase.changed"]
    assert "Current phase: research" in llm.calls[1]["messages"][0]["content"]
    assert llm.calls[1]["tools"] is None  # research tools arrive in M5
    assert sent[-1].state == "happy"


def test_tool_call_cap(store: FakeStore, run) -> None:
    llm = FakeLLM(*[call("get_profile", {}) for _ in range(7)], text("done"))
    sent = run(llm, user_text="hi")
    assert len([m for m in sent if m.type == "tool_event" and m.status == "started"]) == 6
    assert llm.calls[-1]["tools"] is None
    assert "tool limit" in llm.calls[-1]["messages"][-1]["content"]


def test_llm_down_says_template(store: FakeStore, run) -> None:
    sent = run(FakeLLM(LLMUnavailable("both down")), user_text="नमस्कार")
    assert sent[-2].text.startswith("माफ करा")
    assert store.messages[-1]["provider"] == "template"


def test_cjk_is_stripped(store: FakeStore, run) -> None:
    sent = run(FakeLLM(text("च核 करा")), user_text="hi")
    assert sent[-2].text == "च करा"


def test_ui_event_goes_to_model_as_user_note(store: FakeStore, run) -> None:
    llm = FakeLLM(text("छान!"))
    run(llm, ui_event="The user confirmed the profile card.")
    assert store.messages[0]["role"] == "system" and store.messages[0]["input_mode"] == "ui"
    assert llm.calls[0]["messages"][-1] == {
        "role": "user",
        "content": "[UI event] The user confirmed the profile card.",
    }


def test_claimed_card_without_tool_gets_one_nudge(store: FakeStore, run) -> None:
    llm = FakeLLM(
        text("SSC: 2023. Please check the card and tap Confirm."),
        call("propose_profile_update", {"updates": {"ssc_year": 2023}}),
        text("Card ready."),
    )
    sent = run(llm, user_text="2023")
    assert [m.kind for m in sent if m.type == "card"] == ["confirm_profile"]
    assert llm.calls[1]["messages"][-1]["content"].startswith("[system check]")
    assert store.proposals[0]["updates"] == {"ssc_year": 2023}


def test_card_mention_with_pending_card_is_fine(store: FakeStore, run) -> None:
    store.create_proposal(None, "u1", {"session_id": "s1", "updates": {"dob": "2005-05-12"}})
    llm = FakeLLM(text("Please tap Confirm on the card above."))
    run(llm, user_text="ok")
    assert len(llm.calls) == 1  # a card is waiting: no nudge
