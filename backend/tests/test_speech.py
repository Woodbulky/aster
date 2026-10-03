import asyncio
import json
import logging

import pytest

from app.agent import orchestrator
from app.config import Settings
from app.llm.client import Chunk
from app.speech import router as speech
from app.speech import stream
from app.speech.base import SpeechUnavailable, Transcript
from app.speech.sentences import SentenceSplitter, normalize_for_tts
from app.ws import voice
from tests.conftest import FakeStore
from tests.test_agent import text
from tests.test_ws import HELLO, until


@pytest.fixture(autouse=True)
def _fresh_breakers() -> None:
    speech.breakers.clear()


# ---------- sentences ----------
def test_splitter_streams_sentences_in_order() -> None:
    sp = SentenceSplitter()
    out: list[str] = []
    for d in ["नमस्कार! तुमचं नाव काय आहे", " ते सांगा. फी ₹1", ",200.50 आहे आणि हे वाक्य", " संपले।", " शेवट"]:
        out += sp.feed(d)
    out += sp.flush()
    assert out == [
        "नमस्कार! तुमचं नाव काय आहे ते सांगा.",  # "नमस्कार!" alone is under 25 chars
        "फी ₹1,200.50 आहे आणि हे वाक्य संपले।",  # the dots in the amount do not split
        "शेवट",
    ]


def test_first_chunk_may_end_at_a_comma() -> None:
    sp = SentenceSplitter()
    out = sp.feed("ठीक आहे आरव, तुमची जन्मतारीख, आणि तुमचा पूर्ण पत्ता सांगा. मग पुढे, जाऊ.")
    assert out == ["ठीक आहे आरव, तुमची जन्मतारीख,", "आणि तुमचा पूर्ण पत्ता सांगा."]  # later: no comma cuts
    assert sp.flush() == ["मग पुढे, जाऊ."]


def test_splitter_caps_long_runs() -> None:
    sp = SentenceSplitter()
    parts = sp.feed("शब्द " * 100)
    assert parts and all(len(p) <= 220 for p in parts)


def test_normalize_for_tts() -> None:
    assert (
        normalize_for_tts("Income ₹2,50,000 by 05/08/2026")
        == "Income 250000 rupees by 5 August 2026"
    )
    assert normalize_for_tts("Account XXXX XXXX 4417, **ok**") == "Account ending in 4417, ok"
    assert normalize_for_tts("DOB 2005-05-12") == "DOB 12 May 2005"
    assert normalize_for_tts("Aadhaar 1234 5678 9012, A/c 001122334455667") == (
        "Aadhaar ending in 9012, A/c ending in 5667"
    )
    assert normalize_for_tts("धन्यवाद! 🙏🌟") == "धन्यवाद! "


# ---------- router ----------
class FakeSTT:
    def __init__(self, name: str, result: Transcript | Exception, delay: float = 0) -> None:
        self.name, self.result, self.delay, self.calls = name, result, delay, 0

    async def transcribe(self, audio: bytes, mime: str, lang_hint: str | None) -> Transcript:
        self.calls += 1
        await asyncio.sleep(self.delay)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def test_stt_falls_back_and_breaker_skips() -> None:
    bad = FakeSTT("sarvam", RuntimeError("401 bad key"))
    gpu = FakeSTT("local_gpu", Transcript(text="नमस्कार", lang="mr", provider="local_gpu"))
    s = Settings()
    for _ in range(4):
        tr = asyncio.run(speech.transcribe(s, b"x", "audio/wav", "mr", chain=[bad, gpu]))
        assert tr.provider == "local_gpu"
    assert bad.calls == 3  # breaker open after 3 failures: the 4th call skips sarvam
    assert gpu.calls == 4


def test_stt_timeout_moves_on() -> None:
    slow = FakeSTT("sarvam", Transcript(text="x", lang="hi", provider="sarvam"), delay=1)
    gpu = FakeSTT("local_gpu", Transcript(text="y", lang="hi", provider="local_gpu"))
    s = Settings(stt_timeout_s=0.05)
    assert asyncio.run(speech.transcribe(s, b"x", "audio/wav", "hi", chain=[slow, gpu])).text == "y"


def test_all_down_raises() -> None:
    with pytest.raises(SpeechUnavailable):
        asyncio.run(speech.synthesize(Settings(), "hello", "en", chain=[]))


def test_bad_sarvam_key_chain_still_has_local_gpu() -> None:
    assert [p.name for p in speech.stt_chain(Settings(sarvam_api_key="bad"))] == [
        "sarvam",
        "local_gpu",
    ]
    assert (
        speech.tts_chain(Settings(_env_file=None)) == []
    )  # no key -> tts_unavailable -> browser speaks


# ---------- speaker ----------
def test_speaker_sends_in_order_and_marks_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    async def synth(_s, t: str, lang: str):
        if "fail" in t:
            raise SpeechUnavailable("tts")
        await asyncio.sleep(0.05 if "first" in t else 0)  # the first sentence finishes last
        return t.encode(), "audio/mpeg"

    monkeypatch.setattr(stream, "synthesize", synth)
    got: list[tuple[int, str, bool]] = []

    async def emit(seq, t, audio):
        got.append((seq, t, audio is not None))

    async def go() -> stream.Speaker:
        sp = stream.Speaker(Settings(), "mr", emit)
        sp.feed("this is the first sentence here. this one will fail on purpose. ")
        sp.feed("and the last one is short")
        await sp.finish()
        return sp

    sp = asyncio.run(go())
    assert got == [
        (0, "this is the first sentence here.", True),
        (1, "this one will fail on purpose.", False),
        (2, "and the last one is short", True),
    ]
    assert sp.first_audio_at is not None


# ---------- WS voice ----------
def frames(ws, type_: str) -> tuple[list[dict], list[bytes]]:
    """JSON messages up to type_, plus the binary audio frames seen on the way; each binary
    frame must directly follow a tts_audio header."""
    msgs: list[dict] = []
    audio: list[bytes] = []
    while not msgs or msgs[-1]["type"] != type_:
        m = ws.receive()
        if m.get("bytes") is not None:
            assert msgs[-1]["type"] == "tts_audio"
            audio.append(m["bytes"])
        else:
            msgs.append(json.loads(m["text"]))
    return msgs, audio


@pytest.fixture
def voice_io(monkeypatch: pytest.MonkeyPatch):
    seen: dict = {}

    async def transcribe(_s, audio: bytes, mime: str, lang_hint):
        seen.update(audio=audio, mime=mime, hint=lang_hint)
        if audio == b"silence":
            return Transcript(text="", lang="mr", provider="sarvam")
        return Transcript(text="माझं नाव आरव आहे", lang="hi", provider="sarvam")

    async def synth(_s, t: str, lang: str):
        return b"MP3" + t.encode(), "audio/mpeg"

    monkeypatch.setattr(voice.speech, "transcribe", transcribe)
    monkeypatch.setattr(stream, "synthesize", synth)
    return seen


def test_voice_turn(client, store: FakeStore, sid: str, voice_io, caplog) -> None:
    c, llm = client
    store.messages.append({"id": "m0", "session_id": sid, "role": "user", "content": "hi"})
    llm.rounds += [text("नमस्ते आरव! आपकी जन्म तिथि क्या है? बताइए।")]
    caplog.set_level(logging.DEBUG)
    with c.websocket_connect(f"/ws/session/{sid}") as ws:
        ws.send_json(HELLO)
        until(ws, "ready")
        ws.send_json({"type": "audio_start", "mime": "audio/wav", "lang_hint": "mr"})
        ws.send_bytes(b"RIFFaudio")
        ws.send_json({"type": "audio_end"})
        got, audio = frames(ws, "turn_metrics")
        assert got[0] == {
            "type": "transcript",
            "text": "माझं नाव आरव आहे",
            "lang": "hi",
            "provider": "sarvam",
        }
        final = next(m for m in got if m["type"] == "assistant_message")
        assert (
            final["lang"] == "mr"
        )  # reply follows the toggle (hello.lang), not the detected speech
        headers = [m for m in got if m["type"] == "tts_audio"]
        assert [h["seq"] for h in headers] == [0, 1] and headers[0]["mime"] == "audio/mpeg"
        assert len(audio) == 2 and all(a.startswith(b"MP3") for a in audio)
        metrics = got[-1]
        assert metrics["stt_provider"] == "sarvam" and metrics["first_audio_ms"] is not None
    assert voice_io == {"audio": b"RIFFaudio", "mime": "audio/wav", "hint": "mr"}
    user = [m for m in store.messages if m["role"] == "user"][-1]
    assert (user["input_mode"], user["lang"]) == ("voice", "hi")  # what was actually spoken
    logs = caplog.text
    assert "आरव" not in logs and "RIFFaudio" not in logs  # no transcripts or audio in logs


def test_empty_transcript_and_bad_audio(client, store: FakeStore, sid: str, voice_io) -> None:
    c, llm = client
    store.messages.append({"id": "m0", "session_id": sid, "role": "user", "content": "hi"})
    with c.websocket_connect(f"/ws/session/{sid}") as ws:
        ws.send_json(HELLO)
        until(ws, "ready")
        ws.send_bytes(b"stray")  # no audio_start
        assert ws.receive_json()["code"] == "bad_audio"
        ws.send_json({"type": "audio_start", "mime": "audio/wav"})
        ws.send_bytes(b"x" * (voice.MAX_AUDIO_BYTES + 1))
        assert ws.receive_json()["code"] == "bad_audio"
        ws.send_json({"type": "audio_start", "mime": "audio/wav"})
        ws.send_bytes(b"silence")
        ws.send_json({"type": "audio_end"})
        assert until(ws, "error")[-1]["code"] == "no_speech"
    assert llm.calls == []


def test_interrupt_cancels_turn(client, store: FakeStore, sid: str, monkeypatch) -> None:
    c, _ = client
    store.messages.append({"id": "m0", "session_id": sid, "role": "user", "content": "hi"})

    async def slow_llm(_s, messages, *, tools=None, **_kw):
        yield Chunk("gpu", {"content": "एक लंबा जवाब शुरू होता है"})
        await asyncio.sleep(30)
        yield Chunk("gpu", {"content": " never"})

    monkeypatch.setattr(orchestrator, "chat_stream", slow_llm)
    with c.websocket_connect(f"/ws/session/{sid}") as ws:
        ws.send_json(HELLO)
        until(ws, "ready")
        ws.send_json({"type": "user_text", "text": "hello"})
        until(ws, "assistant_delta")
        ws.send_json({"type": "interrupt"})
        assert until(ws, "agent_state")[-1]["state"] == "idle"
        ws.send_json({"type": "ping"})
        assert until(ws, "pong")
    assert not [m for m in store.messages if m["role"] == "assistant"]


def test_ui_event_after_voice_is_spoken_typing_is_not(
    client, store: FakeStore, sid: str, voice_io
) -> None:
    c, llm = client
    store.messages.append({"id": "m0", "session_id": sid, "role": "user", "content": "hi"})
    llm.rounds += [
        text("ठीक है, आगे बढ़ते हैं और अगला सवाल पूछते हैं।"),
        text("बढ़िया, आपका नाम सेव हो गया है। अब जन्म तिथि बताइए।"),
        text("Typed reply, no voice for this one please."),
    ]
    with c.websocket_connect(f"/ws/session/{sid}") as ws:
        ws.send_json(HELLO)
        until(ws, "ready")
        ws.send_json({"type": "audio_start", "mime": "audio/wav", "lang_hint": "mr"})
        ws.send_bytes(b"RIFFaudio")
        ws.send_json({"type": "audio_end"})
        whole_turn(ws)
        ws.send_json({"type": "ui_event", "name": "profile_confirmed", "payload": {}})
        got, audio = whole_turn(ws)  # spoken, in the language the user spoke
        assert audio and _reply(got)["lang"] == "mr"
        ws.send_json({"type": "user_text", "text": "typed"})
        got, audio = whole_turn(ws)
        assert not audio and _reply(got)["lang"] == "mr"


def whole_turn(ws) -> tuple[list[dict], list[bytes]]:
    """Everything up to the agent_state that ends a turn with a reply."""
    got, audio = frames(ws, "assistant_message")
    while got[-1]["type"] != "agent_state" or got[-1]["state"] not in ("idle", "happy"):
        more, a = frames(ws, "agent_state")
        got += more
        audio += a
    return got, audio


def _reply(got: list[dict]) -> dict:
    return next(m for m in got if m["type"] == "assistant_message")


def test_speaker_flush_speaks_short_buffer(monkeypatch: pytest.MonkeyPatch) -> None:
    async def synth(_s, t: str, lang: str):
        return t.encode(), "audio/mpeg"

    monkeypatch.setattr(stream, "synthesize", synth)
    got: list[str] = []

    async def emit(seq, t, audio):
        got.append(t)

    async def go() -> None:
        sp = stream.Speaker(Settings(), "mr", emit)
        sp.feed("धन्यवाद!")  # under 25 chars: held by the splitter
        sp.flush()  # a tool round starts: say it now
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert got == ["धन्यवाद!"]
        await sp.finish()

    asyncio.run(go())


def test_speaker_caps_runaway_replies(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    async def synth(_s, t: str, lang: str):
        calls.append(t)
        return b"x", "audio/mpeg"

    monkeypatch.setattr(stream, "synthesize", synth)

    async def emit(seq, t, audio):
        pass

    async def go() -> None:
        sp = stream.Speaker(Settings(), "mr", emit)
        sp.feed("हे वाक्य पुन्हा पुन्हा येत आहे, थांबत नाही. " * 100)
        await sp.finish()

    asyncio.run(go())
    assert len(calls) == stream.MAX_SENTENCES
