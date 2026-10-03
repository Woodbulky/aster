# ruff: noqa: E501  (tables of portal fields read better on one line)
"""Guided form filling (FORM_FILL.md): the reader/writer split in agent/screen.py, the guardrails
on the writer's output, the in-memory frame store and reading cache, and the WS frame path. The
models' output here is what they could say, not what they should: post-processing must hold
whatever they return."""

import asyncio
import json
import re

import pytest

from app.agent import screen
from app.agent.screen import (
    Frames,
    Reader,
    Reading,
    Written,
    invented_number,
    postprocess,
    recent_talk,
)
from app.speech import stream
from app.speech.base import SpeechUnavailable, Transcript
from app.ws import voice
from tests.conftest import FakeStore
from tests.test_ws import HELLO, until

# The demo account's readiness values (scripts/seed_demo_user.py + specimens).
FIELDS = [
    {"field_key": "full_name", "label": "Full name", "value": "Aarav Sunil Patil", "source": "Aadhaar card · L1"},
    {"field_key": "dob", "label": "Dob", "value": "2005-05-12", "source": "Aadhaar card · L2"},
    {"field_key": "gender", "label": "Gender", "value": "Male", "source": "Aadhaar card · L3"},
    {"field_key": "category", "label": "Category", "value": "Open", "source": "Your profile"},
    {"field_key": "annual_family_income", "label": "Annual family income", "value": "148000", "source": "Your earlier choice"},
    {"field_key": "ssc_percentage", "label": "10th percentage", "value": "87.4", "source": "Class 10 marksheet · L5"},
    {"field_key": "bank_ifsc", "label": "Bank ifsc", "value": "SPCB0001234", "source": "Bank passbook · L2"},
    {"field_key": "aadhaar_last4", "label": "Aadhaar last4", "value": "4417", "source": "Aadhaar card · L4"},
    {"field_key": "bank_account_last4", "label": "Bank account last4", "value": "4417", "source": "Bank passbook · L4"},
]  # fmt: skip
DONE = "Everything on this page looks filled. Check it, then go to the next step."
NO_WRITER = (
    "I can see your page, but I can't work out the next step right now. Ask me again in a moment."
)


def rd(kind: str, fields: list, buttons: list[str] = ()) -> Reading:
    """A reading; a field is a label, or a dict of SeenField values."""
    rows = [{"label": f} if isinstance(f, str) else f for f in fields]
    return Reading.model_validate(
        {"page_kind": kind, "page_title": "t", "fields": rows, "buttons": list(buttons)}
    )


def wr(
    label: str = "", key: str = "", said: str = "", value: str = "", src: str = "not_known"
) -> Written:
    return Written(
        field_label=label, field_key=key, value=value, instruction=said, answer_source=src
    )  # type: ignore[arg-type]


def shown(g) -> str:
    """Everything the user sees or hears from one guidance."""
    parts = [g.instruction] + [
        str(x) for f in [*g.fields, g.target] if f for x in (f.value, f.option_text, f.note) if x
    ]
    return " | ".join(parts)


# ---------- sensitive pages: templates only, whatever the writer says ----------
@pytest.mark.parametrize(
    "kind,labels,template",
    [
        ("login", ["Username", "Password"], "username and password yourself"),
        ("otp", ["Enter OTP"], "type the OTP yourself"),
        ("captcha", ["Type the characters"], "captcha yourself"),
        ("payment", ["Card number"], "payment page"),
        ("submit_confirm", ["I declare"], "you can submit"),
        ("review", [{"label": "Full Name", "appears_filled": True}], "you can submit"),
        # the reader calls it a form, but a secret field makes it sensitive anyway
        ("form", ["Full name", "Password"], "username and password yourself"),
        ("form", ["One Time Password (OTP)"], "username and password yourself"),
        ("other", ["Enter OTP sent to your mobile"], "type the OTP yourself"),
    ],
)
def test_sensitive_pages_pause_and_suggest_nothing(kind, labels, template) -> None:
    # an invented OTP in the writer's text, seen live: "use 123456 for this mock portal"
    w = wr("Full name", "full_name", "Enter 123456 and click Verify", "Aarav Sunil Patil")
    g = postprocess(rd(kind, labels), w, FIELDS, "en", "f1")
    assert g.sensitive and g.target is None
    assert template in g.instruction
    assert "123456" not in shown(g) and "Aarav" not in shown(g)


@pytest.mark.parametrize("button", ["Final Submit", "Submit Application", "अंतिम सबमिट"])
def test_a_final_submit_button_pauses_whatever_the_page_kind(button) -> None:
    # seen live: the mock submit page came back "review" with its rows as unfilled fields
    g = postprocess(rd("review", ["Full Name"], ["Edit", button]), wr(), FIELDS, "en", "f")
    assert g.sensitive and g.page_kind == "submit_confirm"


def test_a_review_page_with_a_submit_button_stays_paused() -> None:
    g = postprocess(rd("review", ["Full Name"], ["Edit", "Submit"]), wr(), FIELDS, "en", "f")
    assert g.sensitive


def test_an_empty_form_called_review_is_a_form() -> None:
    # seen live: the empty application form came back "review"
    r = rd("review", ["Annual Family Income"], ["Save Draft", "Save & Next"])
    w = wr("Annual Family Income", "annual_family_income", "", "148000", "checked_value")
    g = postprocess(r, w, FIELDS, "en", "f")
    assert not g.sensitive and g.target and g.target.value == "148000"


# ---------- the value whitelist ----------
def test_a_checked_value_is_said_from_the_template_in_the_portal_format() -> None:
    r = rd("form", ["Date of Birth (DD/MM/YYYY)", "Annual Family Income"])
    w = wr(
        "Date of Birth (DD/MM/YYYY)", "dob", "Type 12/05/2005 here.", "12/05/2005", "checked_value"
    )
    g = postprocess(r, w, FIELDS, "en", "f")
    assert g.target is g.fields[0] and g.target.value == "12/05/2005"
    assert g.target.source == "Aadhaar card"
    assert g.instruction == "This box is Date of Birth (DD/MM/YYYY). Type 12/05/2005."
    mr = postprocess(r, w, FIELDS, "mr", "f")
    assert mr.instruction == "हा रकाना Date of Birth (DD/MM/YYYY) चा आहे. यात 12/05/2005 लिहा."


def test_a_value_that_is_not_the_checked_one_is_never_said() -> None:
    r = rd("form", ["Applicant Name", "Income"])
    # the old profile income, and a made-up name: dropped for the checked value's template
    for w in (
        wr("Income", "annual_family_income", "Type 120000.", "120000", "checked_value"),
        wr("Applicant Name", "full_name", "Type Rahul Sharma.", "Rahul Sharma", "checked_value"),
    ):
        g = postprocess(r, w, FIELDS, "en", "f", question="what do I type?")
        assert "120000" not in shown(g) and "Rahul" not in shown(g)
        assert g.target and g.target.value in ("148000", "Aarav Sunil Patil")
    # a "checked value" for a key it was never given: no value, no claim
    w = wr("Mobile number", "mobile", "Type 9876543210.", "9876543210", "checked_value")
    g = postprocess(rd("form", ["Mobile number"]), w, FIELDS, "en", "f")
    assert g.target and g.target.value is None and "9876543210" not in shown(g)
    assert g.instruction == NO_WRITER


def test_a_choice_is_chosen_from_the_visible_options() -> None:
    # seen live: "This box is Gender *. Type Male." for a dropdown
    r = rd("form", [{"label": "Gender", "type": "radio", "options": ["पुरुष", "स्त्री"]}])
    g = postprocess(r, wr("Gender", "gender", "", "Male", "checked_value"), FIELDS, "hi", "f")
    assert g.target and g.target.option_text == "पुरुष"
    assert g.instruction == "Gender में “पुरुष” चुनिए।"
    closed = rd("form", [{"label": "Category", "type": "dropdown"}])
    g = postprocess(
        closed, wr("Category", "category", "", "Open", "checked_value"), FIELDS, "en", "f"
    )
    assert g.instruction == "In Category, choose “Open”."


def test_a_question_is_answered_in_the_writers_words_but_checked() -> None:
    r = rd("form", ["Income"])
    said = "It is your whole family's yearly income, 1,48,000 from your certificate."
    w = wr("Income", "annual_family_income", said, "1,48,000", "checked_value")
    g = postprocess(r, w, FIELDS, "en", "f", question="what income?")
    assert g.instruction == said and g.target and g.target.value == "148000"


# ---------- identifiers (guardrail 6) ----------
@pytest.mark.parametrize(
    "label,key",
    [
        ("Aadhaar Number", "aadhaar_last4"),
        ("Aadhaar Number", ""),
        ("आधार क्रमांक", ""),
        ("Bank Account Number", "bank_account_last4"),
        ("A/c No.", ""),
    ],
)
def test_identifiers_are_never_suggested(label, key) -> None:
    w = wr(label, key, f"Type 234567894417 in {label}.", "4417", "checked_value")
    g = postprocess(rd("form", [label]), w, FIELDS, "en", "f1")
    f = g.fields[0]
    assert f.identifier and f.value is None and f.option_text is None
    assert g.target is f and "type the number yourself from your" in g.instruction
    assert not re.search(r"\d{4}", shown(g))  # not even the last 4


@pytest.mark.parametrize(
    "label", ["Applicant Full Name (as per Aadhaar)", "Name on Aadhaar Card", "Account Holder Name"]
)
def test_a_name_label_mentioning_aadhaar_is_not_an_identifier(label) -> None:
    w = wr(label, "full_name", "", "Aarav Sunil Patil", "checked_value")
    g = postprocess(rd("form", [label]), w, FIELDS, "en", "f")
    assert not g.fields[0].identifier and g.fields[0].value == "Aarav Sunil Patil"


@pytest.mark.parametrize(
    "label",
    [
        "Aadhaar No.",
        "Aadhaar Number",
        "Aadhaar *",
        "आधार क्रमांक",
        "UID",
        "Bank A/c No",
        "Account Number",
    ],
)
def test_identifier_labels(label) -> None:
    assert screen._identifier(None, label)


def test_identifiers_are_not_shown_to_the_models() -> None:
    keys = {f["field_key"] for f in screen._model_fields(FIELDS)}
    assert "aadhaar_last4" not in keys and "bank_account_last4" not in keys and "dob" in keys
    assert {"field_key": "dob", "label": "Dob", "value": "12/05/2005"} in screen._model_fields(
        FIELDS
    )


# ---------- free text from the writer ----------
def test_unconfirmed_numbers_are_stripped_from_the_writer_output() -> None:
    """Any 3+ digit number that is not a checked value never reaches the user."""
    for said in ("Use 482913 to continue.", "Your application number is 2026-77812.", "Type 4417."):
        g = postprocess(rd("form", ["Is this a renewal?"]), wr(said=said), FIELDS, "en", "f")
        assert not re.search(r"\d{3}", shown(g)), said
        assert g.instruction == NO_WRITER
    assert invented_number("Type 1,48,000 here", FIELDS) is False
    assert invented_number("Type 150000 here", FIELDS) is True
    assert invented_number("Click Next on page 2", FIELDS) is False


def test_a_quoted_button_or_answer_not_on_the_reading_is_dropped() -> None:
    """Seen live: "Click 'Next'" with no Next button; "'Yes'" for a question with no value."""
    r = rd("form", [{"label": "Is admitted under EWS seat?", "type": "radio"}], ["Save", "Cancel"])
    for said in (
        "Click the 'Next' button to proceed.",
        "Click 'Yes' for 'Is admitted under EWS seat?'",
    ):
        g = postprocess(r, wr(said=said), FIELDS, "en", "f", question="next")
        assert g.instruction == NO_WRITER, said
    ok = "Click “Save” and don't worry, it's fine."
    assert postprocess(r, wr(said=ok), FIELDS, "en", "f", question="next").instruction == ok


def test_a_box_without_a_value_is_explained() -> None:
    """Seen live: "choose what is true for you" for every question the user has no value for."""
    r = rd(
        "form", [{"label": "Is your parent a farmer?", "type": "radio", "options": ["Yes", "No"]}]
    )
    said = "This asks if your father or mother is a farmer. If yes, choose 'Yes'; if not, choose 'No'. Is your parent a farmer?"
    g = postprocess(r, wr("Is your parent a farmer?", said=said), FIELDS, "en", "f")
    assert g.instruction == said and g.target is g.fields[0] and g.target.value is None


def test_page_done_and_no_reading() -> None:
    r = rd("form", [{"label": "Full name", "appears_filled": True}], ["Save & Next"])
    assert postprocess(r, wr(), FIELDS, "en", "f").instruction == DONE
    said = "Press “Save & Next”."
    assert postprocess(r, wr(said=said), FIELDS, "en", "f").instruction == said
    assert postprocess(r, None, FIELDS, "en", "f").instruction == NO_WRITER
    g = postprocess(None, None, FIELDS, "hi", "f")
    assert g.instruction.startswith("मैं आपकी स्क्रीन नहीं पढ़ पाई") and not g.fields


def test_recent_talk_is_text_only_and_short() -> None:
    msgs = [
        {"role": "user", "content": "No, it is not a renewal application."},
        {"role": "tool", "content": None},
        {"role": "system", "content": "Document read: {...}"},
        {"role": "assistant", "content": "Okay.\n\n" + "x" * 500},
    ]
    talk = recent_talk(msgs).splitlines()
    assert talk[0] == "Student: No, it is not a renewal application."
    assert talk[1].startswith("Aster: Okay. x") and len(talk[1]) == 207 and len(talk) == 2


def test_the_reader_schema_caps_fields_on_one_line() -> None:
    schema = screen.reader_schema()["json_schema"]["schema"]
    assert schema["properties"]["fields"]["maxItems"] == screen.READ_FIELDS == 8
    long = rd("form", [f"Box {i}" for i in range(20)])
    assert len(long.fields) == 8  # a json_object fallback is cut in code


def test_compact_fields_are_parsed() -> None:
    rows = [
        "Gender|radio|0|पुरुष / स्त्री",
        "Annual Family Income|text|1",
        "A|B title|dropdown|0",
        "No type here",
        {"label": "Dict", "type": "date"},
    ]
    r = Reading.model_validate({"fields": rows})  # as the reader writes them
    got = [(f.label, f.type, f.appears_filled, f.options) for f in r.fields]
    assert got == [
        ("Gender", "radio", False, ["पुरुष", "स्त्री"]),
        ("Annual Family Income", "text", True, []),
        ("A|B title", "dropdown", False, []),
        ("No type here", "text", False, []),
        ("Dict", "date", False, []),
    ]


# ---------- the writer: language, provider, audit ----------
class Ctx:
    user_id, session, lang, db = "u1", {"id": "s1", "phase": "form_fill"}, "mr", None


def fake_llm(monkeypatch: pytest.MonkeyPatch, replies: list[str]) -> list[dict]:
    calls: list[dict] = []

    async def chat_stream(s, msgs, **kw):
        calls.append({"msgs": [dict(m) for m in msgs], **kw})
        from app.llm.client import Chunk

        yield Chunk("fallback", {"content": replies[len(calls) - 1]})

    monkeypatch.setattr(screen, "chat_stream", chat_stream)
    return calls


def test_the_writer_replies_in_marathi_when_lang_is_mr(monkeypatch: pytest.MonkeyPatch) -> None:
    english = json.dumps(
        {
            "field_label": "Is this a renewal?",
            "instruction": "This asks if you got it last year. Did you?",
        }
    )
    marathi = json.dumps(
        {
            "field_label": "Is this a renewal?",
            "instruction": "हे विचारतंय की तुम्हाला ही शिष्यवृत्ती गेल्या वर्षी मिळाली होती का. मिळाली होती का?",
        }
    )
    calls = fake_llm(monkeypatch, [english, marathi])
    r = rd("form", ["Is this a renewal?"])
    w, served = asyncio.run(screen.write(None, Ctx, r, FIELDS, None, ""))  # type: ignore[arg-type]
    assert w and w.instruction.startswith("हे विचारतंय") and served == "fallback"
    assert "Write in Marathi only" in calls[0]["msgs"][0]["content"]
    assert "Marathi" in calls[1]["msgs"][-1]["content"]  # the retry says why
    # Groq first, audited as screen text; no image, no identifier, not even its last 4
    assert calls[0]["prefer"] == "fallback" and calls[0]["sensitive_kind"] == "screen_text"
    assert "image_url" not in json.dumps(calls[0]["msgs"]) and "4417" not in json.dumps(
        calls[0]["msgs"]
    )
    # a spoken Aadhaar number does not reach the writer
    calls = fake_llm(monkeypatch, [marathi])
    asyncio.run(screen.write(None, Ctx, r, FIELDS, "माझा आधार 2345 6789 0123 आहे", ""))  # type: ignore[arg-type]
    assert "2345" not in json.dumps(calls[0]["msgs"], ensure_ascii=False) and "0123" in json.dumps(
        calls[0]["msgs"], ensure_ascii=False
    )
    # English twice: no reply, never English to a Marathi user
    fake_llm(monkeypatch, [english, english])
    assert asyncio.run(screen.write(None, Ctx, r, FIELDS, None, "")) == (None, None)  # type: ignore[arg-type]


def test_the_reader_goes_to_the_configured_provider_first(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import Settings

    reply = json.dumps(
        {"page_kind": "form", "fields": ["Gender|radio|0|Male/Female"], "buttons": []}
    )
    calls = fake_llm(monkeypatch, [reply, reply])
    r = asyncio.run(screen.read_screen(Settings(), Ctx, b"jpeg"))  # type: ignore[arg-type]
    assert r and r.fields[0].options == ["Male", "Female"]
    assert calls[0]["prefer"] == "fallback" and calls[0]["sensitive_kind"] == "screen_frame"
    assert calls[0]["response_format"]["type"] == "json_schema"
    gpu = Settings(screen_reader_primary="gpu")
    asyncio.run(screen.read_screen(gpu, Ctx, b"jpeg"))  # type: ignore[arg-type]
    assert calls[1]["prefer"] == "gpu"


def test_a_writer_call_prefers_groq_and_is_audited(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    from tests.test_llm_client import FB, capture_audit, collect, s, sse, use_transport

    rows = capture_audit(monkeypatch)
    seen = use_transport(monkeypatch, lambda r: httpx.Response(200, content=sse("ok")))
    cfg = s(gpu_url_override="https://gpu.example", **FB)
    msgs = [{"role": "user", "content": "hi"}]
    collect(
        cfg, msgs, sensitive_kind="screen_text", user_id="u1", session_id="s1", prefer="fallback"
    )
    assert "fb.example" in str(seen[0].url)  # Groq first although the GPU is up
    assert rows[0][3:] == ("llm.sensitive_fallback", {"provider": "groq", "kind": "screen_text"})


# ---------- the reading cache ----------
def test_frames_keep_the_last_three_in_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    now = [100.0]
    monkeypatch.setattr(screen.time, "monotonic", lambda: now[0])
    fr = Frames()
    for i in range(5):
        fr.put(f"f{i}", bytes([i]), "utterance" if i in (0, 2) else "change")
    assert len(fr) == 3  # f0 is gone
    assert fr.take_utterance() == ("f2", b"\x02")
    assert fr.take_utterance() is None  # used once; "change" frames never answer a question
    fr.put("f5", b"5", "utterance")
    now[0] += screen.FRESH_S + 1
    assert fr.take_utterance() is None  # too old to belong to the user's question


def test_the_reader_reads_the_newest_page_once_in_the_background() -> None:
    async def go() -> None:
        reads: list[bytes] = []

        async def read(frame: bytes):
            reads.append(frame)
            await asyncio.sleep(0.01)
            return rd("form", [frame.decode()])

        rdr = Reader(read)
        rdr.refresh("a", b"A")
        rdr.refresh("b", b"B")  # while A is read: queued
        rdr.refresh("c", b"C")  # replaces B: only the newest page is worth reading
        fid, r = await rdr.current()
        assert (fid, r.fields[0].label, reads) == ("c", "C", [b"A", b"C"])
        assert await rdr.current() == (fid, r) and len(reads) == 2  # cached: no new read

    asyncio.run(go())


# ---------- WS: share -> form_fill -> frame -> guidance (+ pause), nothing stored ----------
JPEG = b"\xff\xd8" + b"S" * 5000  # a stand-in frame; only its bytes matter here


@pytest.fixture
def fill(client, store: FakeStore, sid: str, monkeypatch: pytest.MonkeyPatch):
    from app.db import supabase as repo

    store.sessions[sid]["phase"] = "ready"
    store.messages.append({"id": "m0", "session_id": sid, "role": "user", "content": "hi"})
    monkeypatch.setattr(repo, "list_flags", lambda *a, **k: [])
    monkeypatch.setattr(screen, "readiness", lambda *a: {"fields": FIELDS})
    seen: list[bytes] = []
    readings = iter(
        [
            rd("form", ["Annual Family Income", "Is this a renewal?"]),
            rd("otp", ["Enter OTP"]),
        ]
    )

    async def read_screen(s, ctx, frame):
        seen.append(frame)
        await asyncio.sleep(0.05)  # a read takes a while: the turn starts while it runs
        return next(readings)

    asked: list[str | None] = []

    async def write(s, ctx, r, fields, question, history):
        asked.append(question)
        if question:  # "Renewal?": no value held, explained (and a made-up number, stripped)
            said = "हे विचारतंय की ही शिष्यवृत्ती तुम्हाला आधी मिळाली होती का. अर्ज क्रमांक 77812 आहे."
            return wr("Is this a renewal?", said=said), "fallback"
        return wr(
            "Annual Family Income", "annual_family_income", "", "148000", "checked_value"
        ), "fallback"

    monkeypatch.setattr(screen, "read_screen", read_screen)
    monkeypatch.setattr(screen, "write", write)

    async def no_tts(*a, **k):  # the client speaks it (tts_unavailable carries the text)
        raise SpeechUnavailable("test")

    async def transcribe(_s, audio, mime, lang_hint):
        return Transcript(text="नूतनीकरण म्हणजे काय?", lang="mr", provider="sarvam")

    monkeypatch.setattr(stream, "synthesize", no_tts)
    monkeypatch.setattr(voice.speech, "transcribe", transcribe)
    return client[0], seen, asked


def frame(ws, reason: str = "manual", data: bytes = JPEG) -> None:
    ws.send_json({"type": "screen_frame", "frame_id": "fr-1", "reason": reason})
    ws.send_bytes(data)


def screen_turn(ws) -> list[dict]:
    """Everything one screen turn sends, through its final idle."""
    got = until(ws, "guidance")
    while not (got[-1]["type"] == "agent_state" and got[-1]["state"] == "idle"):
        got.append(ws.receive_json())
    return got


def test_ws_guides_answers_from_the_cache_then_pauses_on_otp(
    fill, store: FakeStore, sid: str
) -> None:
    c, seen, asked = fill
    with c.websocket_connect(f"/ws/session/{sid}") as ws:
        ws.send_json(HELLO)
        until(ws, "ready")
        frame(ws)  # still "ready": kept, not read
        ws.send_json({"type": "ui_event", "name": "screen_share_started", "payload": {}})
        assert until(ws, "phase")[-1]["phase"] == "form_fill"
        frame(ws)
        first = screen_turn(ws)
        g = next(m for m in first if m["type"] == "guidance")
        assert g["target"]["value"] == "148000" and not g["sensitive"]
        assert g["instruction"] == "हा रकाना Annual Family Income चा आहे. यात 148000 लिहा."
        # a question about the same page: its utterance frame is not read, the cache answers
        frame(ws, "utterance", JPEG + b"same page")
        ws.send_json({"type": "audio_start", "mime": "audio/wav", "lang_hint": "mr"})
        ws.send_bytes(b"RIFFaudio")
        ws.send_json({"type": "audio_end"})
        cached = screen_turn(ws)
        answer = next(m for m in cached if m["type"] == "guidance")
        assert len(seen) == 1  # no vision call for it
        # the made-up number dropped the writer's text
        assert (
            answer["instruction"]
            == "मला तुमचं पान दिसतंय, पण आत्ता पुढची पायरी सांगता येत नाहीये. थोड्या वेळाने पुन्हा विचारा."
        )
        assert "77812" not in str(cached)
        assert not any(m.get("detail") == "Looking at your screen" for m in cached)
        frame(ws, data=JPEG + b"2")
        second = screen_turn(ws)
        otp = next(m for m in second if m["type"] == "guidance")
        assert otp["sensitive"] and {"type": "pause_guidance", "reason": "otp"} in second
        ws.send_json({"type": "screen_frame", "frame_id": "big", "reason": "manual"})
        ws.send_bytes(b"x" * 1_600_000)
        assert until(ws, "error")[-1]["code"] == "bad_frame"
    assert asked == [None, "नूतनीकरण म्हणजे काय?"]  # no writer on the OTP page
    spoken = [m["text"] for m in first + cached + second if m["type"] == "tts_unavailable"]
    # a manual frame: "let me look" first (a read was under way); the cached answer: none
    assert spoken[0] == "मी तुमची स्क्रीन बघते…" and spoken.count("मी तुमची स्क्रीन बघते…") == 2
    assert "OTP स्वतः टाका" in " ".join(spoken)
    assert len(seen) == 2  # the frame sent before form_fill was never read
    assert ("phase.changed", {"from": "ready", "to": "form_fill"}) in store.audit
    # Guardrail 7: no frame bytes anywhere in what was stored
    stored = repr(store.messages) + repr(store.audit)
    assert "SSSSSSSS" not in stored and "\xff\xd8" not in stored


def test_ws_share_needs_ready(client, store: FakeStore, sid: str, monkeypatch) -> None:
    from app.db import supabase as repo

    monkeypatch.setattr(repo, "list_flags", lambda *a, **k: [])
    store.sessions[sid]["phase"] = "documents"
    store.messages.append({"id": "m0", "session_id": sid, "role": "user", "content": "hi"})
    with client[0].websocket_connect(f"/ws/session/{sid}") as ws:
        ws.send_json(HELLO)
        until(ws, "ready")
        ws.send_json({"type": "ui_event", "name": "screen_share_started", "payload": {}})
        assert until(ws, "error")[-1]["code"] == "not_ready"
    assert store.sessions[sid]["phase"] == "documents"


def test_ws_frames_do_not_use_the_message_limit(fill, sid: str) -> None:
    c, _, _ = fill
    with c.websocket_connect(f"/ws/session/{sid}") as ws:
        ws.send_json(HELLO)
        until(ws, "ready")
        for _ in range(20):  # 20 change frames: 40 WS messages, none read (not form_fill)
            frame(ws, "change")
        for _ in range(29):
            ws.send_json({"type": "ping"})
            assert ws.receive_json()["type"] == "pong"
