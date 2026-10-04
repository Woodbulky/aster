import json
from types import SimpleNamespace
from typing import Any

import pytest

from app.agent import orchestrator
from app.agent.prompts import t
from app.agent.tools import Ctx, run_tool
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
    res = run_tool(ctx(store), "set_form", {"scheme_key": "demo.obc_aid"})  # in onboarding
    assert not res.ok and "not available" in res.error
    assert store.sessions["s1"].get("scheme_key") is None


def test_bad_json_args(store: FakeStore) -> None:
    assert run_tool(ctx(store), "get_profile", "{not json").error == "arguments are not valid JSON"


def test_explain_why_asked_uses_template(store: FakeStore) -> None:
    res = run_tool(ctx(store, "mr"), "explain_why_asked", {"field_key": "annual_family_income"})
    assert "उत्पन्न" in res.data["text"] and res.data["source"]
    res = run_tool(ctx(store, "en"), "explain_why_asked", {"field_key": "pet_name"})
    assert res.data["text"].startswith("I ask so")


@pytest.mark.parametrize(
    "args",
    [
        {},  # neither
        {"scheme_key": "demo.obc_aid", "scheme_name": "OBC Aid"},  # both
        {"scheme_key": "demo.nope"},  # not a pack
        {"scheme_key": "demo.draft_one"},  # draft packs are not offered in tests/prod
        {"scheme_key": "demo.obc_aid", "portal_url": "https://evil.x"},  # URL never from the LLM
        {"scheme_name": "ab"},  # too short to research
    ],
)
def test_set_form_rejects(store: FakeStore, args: dict) -> None:
    store.sessions["s1"]["phase"] = "choose_form"
    assert not run_tool(ctx(store), "set_form", args).ok
    assert store.audit == []


def test_set_form(store: FakeStore) -> None:
    store.sessions["s1"]["phase"] = "choose_form"
    res = run_tool(ctx(store), "set_form", {"scheme_key": "demo.obc_aid"})
    assert res.ok
    s = store.sessions["s1"]
    assert (s["portal"], s["scheme_key"], s["scheme_name"]) == ("demo", "demo.obc_aid", "OBC Aid")
    assert s["portal_url"] == "https://scholarships.demo.gov.in"  # from _portal.json
    assert store.audit[-1][0] == "form.set"
    # any other scholarship: just the name, no URL until research finds one
    res = run_tool(ctx(store), "set_form", {"scheme_name": "Tata Capital Pankh"})
    assert res.ok and not res.data["known_rules"]
    assert (s["scheme_key"], s["scheme_name"], s["portal_url"]) == (
        None,
        "Tata Capital Pankh",
        None,
    )


def test_suggest_schemes_ranks_by_fit(store: FakeStore) -> None:
    store.sessions["s1"]["phase"] = "choose_form"
    store.profile.update(COMPLETE_PROFILE)  # OBC, income 1.48 lakh, 12th 81.5%
    res = run_tool(ctx(store), "suggest_schemes", {})
    opts = res.card.payload["options"]
    assert res.card.kind == "scheme_suggestions"
    assert [o["scheme_key"] for o in opts] == ["demo.obc_aid", "demo.open_merit"]  # no draft
    assert (opts[0]["met"], opts[0]["not_met"], opts[0]["unknown"]) == (2, 0, 2)
    assert (opts[1]["met"], opts[1]["not_met"]) == (1, 1)
    store.profile["category"] = "Open"
    opts = run_tool(ctx(store), "suggest_schemes", {}).card.payload["options"]
    assert opts[0]["scheme_key"] == "demo.open_merit"
    assert not run_tool(ctx(store), "suggest_schemes", {"portal": "nowhere"}).ok


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
    llm = FakeLLM(call("set_form", {"scheme_key": "demo.obc_aid"}), text("ठीक आहे!"))
    sent = run(llm, user_text="OBC Aid")
    # onboarding -> choose_form at the start of the turn, -> research after set_form
    assert [m.phase for m in sent if m.type == "phase"] == ["choose_form", "research"]
    assert store.sessions["s1"]["phase"] == "research"
    assert [a for a, _ in store.audit] == ["phase.changed", "form.set", "phase.changed"]
    assert "Current phase: research" in llm.calls[1]["messages"][0]["content"]
    assert "get_knowledge_pack" in {t["function"]["name"] for t in llm.calls[1]["tools"]}
    assert sent[-1].state == "happy"


def test_tool_call_cap(store: FakeStore, run) -> None:
    llm = FakeLLM(*[call("get_profile", {}) for _ in range(7)], text("done"))
    sent = run(llm, user_text="hi")
    assert len([m for m in sent if m.type == "tool_event" and m.status == "started"]) == 6
    assert llm.calls[-1]["tools"] is None
    assert "tool limit" in llm.calls[-1]["messages"][-1]["content"]


def test_repeated_lookup_not_rerun(store: FakeStore, run, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.agent.tools import ToolResult

    ran: list[str] = []

    async def fake_tool(_ctx, _send, name, args):
        ran.append(name)
        return ToolResult(ok=True, data={"results": []})

    monkeypatch.setattr(orchestrator, "run_tool_ui", fake_tool)
    q = {"query": "Shahu Maharaj"}
    llm = FakeLLM(call("search_web", q), call("search_web", q), text("done"))
    run(llm, user_text="shahu maharaj")
    assert ran == ["search_web"]
    assert "already made this exact call" in llm.calls[-1]["messages"][-1]["content"]


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
        "content": "[UI event] The user confirmed the profile card.",  # same language: no note
    }


def test_reply_language_note_on_latest_user_turn_only(store: FakeStore, run) -> None:
    """The toggle switched to Hindi while the history is Marathi: the request carries a Hindi
    note on the newest user turn; nothing stored is changed."""
    store.messages.append({"id": "h1", "session_id": "s1", "role": "user", "content": "नमस्कार"})
    llm = FakeLLM(text("नमस्ते!"))
    run(llm, ctx(store, lang="hi"), user_text="माझं नाव आरव आहे.", input_mode="voice", user_lang="mr")
    users = [m["content"] for m in llm.calls[0]["messages"] if m["role"] == "user"]
    assert users == ["नमस्कार", "माझं नाव आरव आहे.\n\n" + t("hi", "reply_in")]
    stored = store.messages[-2]  # the user's turn, then the reply
    assert (stored["content"], stored["lang"]) == ("माझं नाव आरव आहे.", "mr")
    assert store.messages[-1]["lang"] == "hi"


def test_language_acknowledgements_are_dropped(store: FakeStore, run) -> None:
    """Seen live: after a switch to Hindi every reply began "ठीक है, अब से मैं केवल हिंदी में ही
    जवाब दूँगा।" and the model kept copying it from the history. It is removed from the history
    the model sees and from the stored reply; normal sentences stay."""
    ack = "ठीक है, अब से मैं केवल हिंदी में ही जवाब दूँगा।"
    store.messages += [
        {"id": "h1", "session_id": "s1", "role": "assistant", "content": f"{ack}\n\nआपका ज़िला?"},
        {"id": "h2", "session_id": "s1", "role": "user", "content": "Thane"},
        {"id": "h3", "session_id": "s1", "role": "assistant", "content": ack},
    ]
    llm = FakeLLM(text(f"{ack}\n\nआपकी कैटेगरी क्या है — Open, OBC, SC या ST?"))
    sent = run(llm, ctx(store, lang="hi"), user_text="Hello.")
    seen = [m["content"] for m in llm.calls[0]["messages"][1:]]
    assert seen == ["आपका ज़िला?", "Thane", "Hello."]  # no note: nothing in another language
    final = "आपकी कैटेगरी क्या है — Open, OBC, SC या ST?"
    assert sent[-2].text == final and store.messages[-1]["content"] == final


@pytest.mark.parametrize(
    "text,kept",
    [
        ("Okay, I'll reply only in English. What is your district?", "What is your district?"),
        ("ठीक आहे, आता मी फक्त मराठीत उत्तर देईन. तुमचा जिल्हा?", "तुमचा जिल्हा?"),
        ("Income is ₹1.5 lakh. Is that right?", "Income is ₹1.5 lakh. Is that right?"),
        ("I can help in English, Hindi or Marathi.", "I can help in English, Hindi or Marathi."),
    ],
)
def test_strip_lang_ack(text: str, kept: str) -> None:
    assert orchestrator.strip_lang_ack(text) == kept


@pytest.mark.parametrize(
    "claim",
    [
        "SSC: 2023. Please check the card and tap Confirm.",
        'तुमचं वर्ष पुष्टी करा आणि "Confirm" बटण दाबा.',
    ],
)
def test_claimed_card_without_tool_gets_one_nudge(store: FakeStore, run, claim: str) -> None:
    llm = FakeLLM(
        text(claim),
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


def test_promise_only_reply_switches_scheme(store: FakeStore, run) -> None:
    """Seen live (eligibility step, Groq): "what about this Bajaj finserv scholarship" got three
    "Let me check…" sentences and no tool call. The model is nudged and switches the scheme."""
    store.profile.update(COMPLETE_PROFILE)
    store.sessions["s1"].update(phase="eligibility", scheme_name="Reliance Foundation Scholarship")
    store.research.append(
        {"id": "r1", "session_id": "s1", "scheme": "Reliance Foundation Scholarship",
         "kind": "eligibility", "items": []}
    )  # fmt: skip
    promise = "Let me check the official rules for Bajaj Finserv.\n\nLet me read the page."
    llm = FakeLLM(
        text(promise),
        call("set_form", {"scheme_name": "Bajaj Finserv Scholarship"}),
        # now in research: replies without saved research are nudged (at most twice)
        text("Searching."),
        text("Searching."),
        text("I could not reach the official site; do you have a link?"),
    )
    sent = run(llm, user_text="what about this Bajaj finserv scholarship")
    assert "called no tool" in llm.calls[1]["messages"][-1]["content"]
    assert store.sessions["s1"]["scheme_name"] == "Bajaj Finserv Scholarship"
    assert [m.phase for m in sent if m.type == "phase"] == ["research"]
    assert sent[-2].text == "I could not reach the official site; do you have a link?"
    assert "Let me" not in store.messages[-1]["content"]


@pytest.mark.parametrize(
    "text,only",
    [
        ("Let me check the rules.\n\nI'll read the page.", True),
        ("मैं नियम देखती हूँ।", True),
        ("Per the official rules, 3 of 6 criteria look met. Let me know if you want more.", False),
        ("Your profile is ready!", False),
    ],
)
def test_promise_only(text: str, only: bool) -> None:
    assert orchestrator.promise_only(text) is only


def test_history_drops_promises() -> None:
    rows = [
        {"role": "assistant", "content": "Let me check the rules.\n\nLet me read the page."},
        {"role": "user", "content": "ok"},
        {"role": "assistant", "content": "Let me check. 3 of 6 criteria look met."},
    ]
    assert orchestrator._history(rows) == [
        {"role": "user", "content": "ok"},
        {"role": "assistant", "content": "3 of 6 criteria look met."},
    ]
