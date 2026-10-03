"""WS /ws/session/{id}: the conversation channel (docs/API.md): text, voice in, sentence-streamed
voice out."""

import asyncio
import contextlib
import json
import logging
import time
import uuid
from collections import deque
from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ValidationError

from app.agent import screen
from app.agent.orchestrator import run_tool_ui, run_turn, show_new_flag_cards, sync_phase
from app.agent.tools import Ctx
from app.config import Settings, get_settings
from app.db import supabase as repo
from app.deps import Db, user_from_token
from app.speech import router as speech
from app.speech.base import SpeechUnavailable
from app.speech.stream import Speaker
from app.verify import pipeline
from app.verify.checks import flag_summary
from app.ws.protocol import (
    AgentState,
    AudioEnd,
    AudioStart,
    ClientMsg,
    DocumentProcessed,
    ErrorMsg,
    FlagResolved,
    FormSelected,
    Hello,
    Interrupt,
    PhaseMsg,
    Ping,
    Pong,
    Ready,
    ScreenFrame,
    TranscriptMsg,
    TtsAudio,
    TtsUnavailable,
    UiEvent,
    UserText,
)

router = APIRouter()
log = logging.getLogger(__name__)

HELLO_TIMEOUT_S = 10.0
RATE_LIMIT = 30  # messages per minute (ARCHITECTURE "Security")
MAX_AUDIO_BYTES = 2_000_000  # one utterance
MAX_FRAME_BYTES = 1_500_000  # one JPEG screen frame (<= 1280 px wide)
FRAME_LIMIT = 30  # screen frames per minute, on top of RATE_LIMIT (FORM_FILL: <= 1 per 3 s)
CHANGE_MIN_S = 2.0  # "the screen changed" frames closer than this are kept but not analysed
# Close codes the client must not retry on.
BAD_HELLO, UNAUTHORIZED, NOT_FOUND = 4400, 4401, 4404

UI_EVENT_TEXT = {
    "profile_confirmed": "The user confirmed the profile card; those values are now saved.",
    "profile_rejected": "The user said the card's values are not right. Ask what to correct.",
}


@router.websocket("/ws/session/{session_id}")
async def session_ws(
    ws: WebSocket,
    session_id: uuid.UUID,
    db: Db,
    s: Annotated[Settings, Depends(get_settings)],
) -> None:
    await ws.accept()
    try:
        await _serve(ws, session_id, db, s)
    except WebSocketDisconnect:
        pass  # the client went away mid-turn; everything said so far is already stored


async def _serve(ws: WebSocket, session_id: uuid.UUID, db: Db, s: Settings) -> None:
    wire = asyncio.Lock()  # a tts_audio header and its binary frame must stay adjacent

    async def send(m: BaseModel) -> None:
        async with wire:
            await ws.send_text(m.model_dump_json())

    try:
        hello = ClientMsg.validate_json(await asyncio.wait_for(ws.receive_text(), HELLO_TIMEOUT_S))
    except (TimeoutError, ValidationError, KeyError):
        hello = None
    if not isinstance(hello, Hello):
        await send(ErrorMsg(code="bad_hello", message="first message must be hello"))
        return await ws.close(BAD_HELLO)
    user_id = await asyncio.to_thread(user_from_token, db, hello.token)
    if not user_id:
        await send(ErrorMsg(code="unauthorized", message="sign in again"))
        return await ws.close(UNAUTHORIZED)
    session = await asyncio.to_thread(repo.get_session, db, user_id, str(session_id))
    if not session:  # someone else's session looks the same as a missing one
        await send(ErrorMsg(code="not_found", message="session not found"))
        return await ws.close(NOT_FOUND)

    assistant = await asyncio.to_thread(repo.get_assistant, db, user_id) or {}
    name = assistant.get("assistant_name") or "Aster"
    ctx = Ctx(db=db, user_id=user_id, session=session, lang=hello.lang)
    await sync_phase(ctx, send)
    await send(
        Ready(
            phase=ctx.session["phase"],
            assistant={"name": name, "avatar_id": assistant.get("avatar_id") or "aster"},
        )
    )

    current: asyncio.Task | None = None

    def start(job: Callable[[], Awaitable[None]], *, preempt: bool) -> None:
        """Run a turn in the background so the loop can still receive `interrupt`. A new utterance
        (preempt) cancels the running turn; a UI event waits for it."""
        nonlocal current
        prev = current

        async def run() -> None:
            if prev and not prev.done():
                if preempt:
                    prev.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await prev
            try:
                await job()
            except asyncio.CancelledError:
                with contextlib.suppress(Exception):
                    await send(AgentState(state="idle"))
                raise
            except WebSocketDisconnect:
                pass
            except Exception:
                log.exception("turn crashed")
                with contextlib.suppress(Exception):
                    await send(ErrorMsg(code="turn_failed", message="something went wrong"))
                    await send(AgentState(state="idle"))

        current = asyncio.create_task(run())

    async def emit(message_id: str, lang: str, seq: int, text: str, audio) -> None:
        if audio is None:
            return await send(
                TtsUnavailable(message_id=message_id, seq=seq, text=text, lang=lang)  # type: ignore[arg-type]
            )
        data, mime = audio
        async with wire:
            header = TtsAudio(message_id=message_id, seq=seq, mime=mime)
            await ws.send_text(header.model_dump_json())
            await ws.send_bytes(data)

    def speaker_for(lang: str) -> Callable[[str], Speaker]:
        return lambda mid: Speaker(
            s, lang, lambda seq, text, audio: emit(mid, lang, seq, text, audio)
        )

    spoken = False  # the last user turn was voice; typing switches spoken replies off

    async def text_turn(**kw: str) -> None:
        """Typed text or a UI event. After a voice turn, a UI event reply (e.g. after a card tap)
        is spoken too."""
        nonlocal spoken
        if "user_text" in kw:
            spoken = False
            if ctx.session["phase"] == "form_fill" and (reader.busy or reader.has):
                text = kw["user_text"]  # about the shared screen: the cached reading answers it
                row = {"role": "user", "content": text, "lang": ctx.lang, "input_mode": "text"}
                await asyncio.to_thread(repo.add_message, db, user_id, ctx.session["id"], row)
                return await screen_turn(question=text, announce=True, voice=False)
        voice_out = speaker_for(ctx.lang) if spoken else None
        await run_turn(s, ctx, send, assistant_name=name, speaker_factory=voice_out, **kw)

    frames = screen.Frames()
    # The vision reading of the shared screen, per connection: a new page is read in the
    # background as soon as it arrives; questions about an unchanged page reuse it.
    reader = screen.Reader(lambda frame: screen.read_screen(s, ctx, frame))
    auto: asyncio.Task | None = None  # the guidance turn a page change started
    last_change = 0.0

    async def screen_turn(
        question: str | None = None,
        announce: bool = False,
        voice: bool = True,
        talk: Awaitable[list] | None = None,
    ) -> None:
        speak = speaker_for(ctx.lang) if voice else None
        g = await screen.run_screen_turn(s, ctx, send, reader, question, speak, announce, talk)
        # The page moved on while this turn spoke: guide the newer page too.
        while not question and (reader.busy or reader.frame_id not in (None, g.frame_id)):
            g = await screen.run_screen_turn(s, ctx, send, reader, None, speaker_for(ctx.lang))

    def on_frame(head: ScreenFrame, data: bytes) -> None:
        nonlocal last_change, auto
        frames.put(head.frame_id, data, head.reason)
        if head.reason == "utterance" or ctx.session["phase"] != "form_fill":
            return  # an utterance frame waits for its transcript (voice_turn)
        now = time.monotonic()
        if head.reason == "change":
            if now - last_change < CHANGE_MIN_S:
                return
            last_change = now
        reader.refresh(head.frame_id, data)  # the vision read starts now, in the background
        if head.reason == "change" and auto and not auto.done():
            return  # that turn guides the newest reading
        manual = head.reason == "manual"
        start(lambda: screen_turn(announce=manual), preempt=False)
        auto = current

    async def voice_turn(audio: bytes, head: AudioStart) -> None:
        nonlocal spoken
        t0 = time.monotonic()
        filling = ctx.session["phase"] == "form_fill"
        # Form filling: the recent talk loads while the speech is transcribed (a cached answer
        # is then the writer call alone).
        sid = ctx.session["id"]
        talk = (
            asyncio.ensure_future(asyncio.to_thread(repo.list_messages, db, user_id, sid, 16))
            if filling
            else None
        )
        try:
            tr = await speech.transcribe(s, audio, head.mime, head.lang_hint)
        except SpeechUnavailable:
            await send(ErrorMsg(code="stt_unavailable", message="could not hear that, try typing"))
            return await send(AgentState(state="idle"))
        stt_ms = round((time.monotonic() - t0) * 1000)
        if not tr.text:
            await send(ErrorMsg(code="no_speech", message="I didn't catch that"))
            return await send(AgentState(state="idle"))
        await send(TranscriptMsg(text=tr.text, lang=tr.lang, provider=tr.provider))  # type: ignore[arg-type]
        # Replies follow the reply-language toggle (hello.lang); a language switch reconnects
        # with the new hello. What the user actually spoke is stored on their message.
        spoken = True
        shot = frames.take_utterance() if filling else None
        if filling and (shot or reader.busy or reader.has):
            # The user asked about the screen. An unchanged page uses the cached reading (the
            # client sends a "change" frame instead when the page changed): no vision call.
            if shot and not (reader.busy or reader.has):
                reader.refresh(*shot)
            row = {"role": "user", "content": tr.text, "lang": tr.lang, "input_mode": "voice"}
            await asyncio.to_thread(repo.add_message, db, user_id, ctx.session["id"], row)
            return await screen_turn(question=tr.text, announce=True, talk=talk)
        await run_turn(
            s,
            ctx,
            send,
            assistant_name=name,
            user_text=tr.text,
            input_mode="voice",
            user_lang=tr.lang,
            speaker_factory=speaker_for(ctx.lang),
            t0=t0,
            stt_ms=stt_ms,
            stt_provider=tr.provider,
        )

    if not await asyncio.to_thread(repo.list_messages, db, user_id, ctx.session["id"], 1):
        start(
            lambda: text_turn(
                ui_event="Conversation started. Greet the user warmly and begin your goal."
            ),
            preempt=False,
        )

    loop = asyncio.get_running_loop()

    def document_done(doc_id: str) -> None:
        # The pipeline may finish on another loop or thread: hand the turn to this socket's loop.
        job = lambda: _document_processed(ctx, send, {"document_id": doc_id}, text_turn)  # noqa: E731
        loop.call_soon_threadsafe(lambda: start(job, preempt=False))

    unsubscribe = pipeline.subscribe(ctx.session["id"], document_done)
    # ponytail: per-connection limit; per-user across tabs if abuse shows up.
    recent: deque[float] = deque()
    shots: deque[float] = deque()
    pending: AudioStart | None = None  # audio_start seen, waiting for its binary frame
    audio: bytes | None = None
    shot: ScreenFrame | None = None  # screen_frame seen, waiting for its JPEG

    async def over(times: deque[float], limit: int) -> bool:
        now = time.monotonic()
        while times and now - times[0] > 60:
            times.popleft()
        if len(times) >= limit:
            await send(ErrorMsg(code="rate_limited", message="too many messages, slow down"))
            return True
        times.append(now)
        return False

    try:
        while True:
            frame = await ws.receive()
            if frame["type"] == "websocket.disconnect":
                return
            if shot is not None and frame.get("bytes") is not None:
                head, shot = shot, None
                if len(frame["bytes"]) > MAX_FRAME_BYTES:
                    await send(ErrorMsg(code="bad_frame", message="screen frame too large"))
                else:
                    on_frame(head, frame["bytes"])
                continue
            shot = None
            try:  # screen frames have their own limit; everything else shares RATE_LIMIT
                is_shot = json.loads(frame.get("text") or "{}").get("type") == "screen_frame"
            except (json.JSONDecodeError, AttributeError):
                is_shot = False
            if await over(shots if is_shot else recent, FRAME_LIMIT if is_shot else RATE_LIMIT):
                continue
            if frame.get("bytes") is not None:
                if pending and audio is None and len(frame["bytes"]) <= MAX_AUDIO_BYTES:
                    audio = frame["bytes"]
                else:
                    pending, audio = None, None
                    await send(ErrorMsg(code="bad_audio", message="unexpected or too large audio"))
                continue
            try:
                msg = ClientMsg.validate_json(frame.get("text") or "")
            except ValidationError:
                await send(ErrorMsg(code="bad_message", message="unsupported message"))
                continue
            match msg:
                case Ping():
                    await send(Pong())
                case AudioStart():
                    pending, audio = msg, None
                case AudioEnd():
                    if pending and audio:
                        a, p = audio, pending
                        start(lambda a=a, p=p: voice_turn(a, p), preempt=True)
                    else:
                        await send(ErrorMsg(code="bad_audio", message="audio_end without audio"))
                    pending, audio = None, None
                case ScreenFrame():
                    shot = msg
                case UiEvent(name="screen_share_started"):
                    start(lambda: _screen_share_started(ctx, send), preempt=False)
                case Interrupt():
                    if current and not current.done():
                        current.cancel()  # run() tells the client the agent is idle
                case UserText(text=text):
                    start(lambda text=text: text_turn(user_text=text), preempt=True)
                case UiEvent(name="form_selected", payload=payload):
                    start(
                        lambda payload=payload: _form_selected(ctx, send, payload, text_turn),
                        preempt=False,
                    )
                case UiEvent(name="documents_requested"):
                    start(lambda: _documents_requested(ctx, send, text_turn), preempt=False)
                case UiEvent(name="document_processed", payload=payload):
                    start(
                        lambda payload=payload: _document_processed(ctx, send, payload, text_turn),
                        preempt=False,
                    )
                case UiEvent(name="flag_resolved", payload=payload):
                    start(
                        lambda payload=payload: _flag_resolved(ctx, send, payload, text_turn),
                        preempt=False,
                    )
                case UiEvent(name=event):
                    start(
                        lambda event=event: text_turn(ui_event=UI_EVENT_TEXT[event]), preempt=False
                    )
                case Hello():
                    pass  # already authenticated; reconnects open a new socket
    finally:
        unsubscribe()
        reader.close()
        if current and not current.done():
            current.cancel()


async def _form_selected(ctx: Ctx, send, payload: dict, turn) -> None:
    """A tap on a scheme card runs set_form -> get_knowledge_pack -> check_eligibility in code,
    without asking the LLM (the demo path must not depend on the model's tool calling). The LLM
    turn after it only speaks the summary."""
    try:
        pick = FormSelected.model_validate(payload)
    except ValidationError:
        return await send(ErrorMsg(code="bad_message", message="bad form_selected payload"))
    res = await run_tool_ui(ctx, send, "set_form", {"scheme_key": pick.scheme_key})
    if not res.ok:
        return await send(ErrorMsg(code="form_not_set", message=res.error or "form not set"))
    name = res.data["scheme_name"]
    await sync_phase(ctx, send)  # -> research
    elig = None
    if (await run_tool_ui(ctx, send, "get_knowledge_pack", {})).ok:
        await sync_phase(ctx, send)  # -> eligibility
        elig = await run_tool_ui(ctx, send, "check_eligibility", {})
    if elig and elig.ok:
        criteria = json.dumps(elig.data["criteria"], ensure_ascii=False)
        note = (
            f"The user picked {name}. The eligibility card is on screen: {criteria}. Summarise it "
            "in 2-3 short sentences per the official source, never as a final verdict, and if a "
            "criterion is unknown with an ask_field, ask for that one value. Do not call "
            "check_eligibility again."
        )
    else:
        note = f"The user picked {name} from the suggestions card."
    await turn(ui_event=note)


async def _documents_requested(ctx: Ctx, send, turn) -> None:
    """ "Continue to documents" button on the eligibility card: checklist in code, then speak."""
    res = await run_tool_ui(ctx, send, "request_documents", {})
    if not res.ok:
        return await send(ErrorMsg(code="documents_unavailable", message=res.error or "no scheme"))
    data = json.dumps(res.data, ensure_ascii=False)
    await turn(
        ui_event="The user tapped Continue to documents. The checklist card is on screen: "
        f"{data}. In one or two short sentences, say which required documents to upload first."
    )


async def _document_processed(ctx: Ctx, send, payload: dict, turn) -> None:
    """The client saw a document finish: field review card in code, then a short spoken
    summary."""
    try:
        doc_id = str(DocumentProcessed.model_validate(payload).document_id)
    except ValidationError:
        return await send(ErrorMsg(code="bad_message", message="bad document_processed payload"))
    res = await run_tool_ui(ctx, send, "get_document_status", {"document_id": doc_id})
    if not res.ok:
        return await send(ErrorMsg(code="document_not_found", message=res.error or "not found"))
    data = json.dumps(res.data, ensure_ascii=False)
    if res.data["status"] != "read":
        await turn(ui_event=f"Document not read: {data}. Say so in one sentence with the reason.")
        return
    flags = await show_new_flag_cards(ctx, send)
    note = (
        f"Document read: {data}. The field review card is on screen. In one or two short "
        "sentences say it was read and what it shows. If not_found_on_document is not empty, "
        "name those fields and ask the user to check them on the card; the document itself was "
        "read fine."
    )
    if flags:
        note += (
            f" Checking it against the other documents and the profile found: "
            f"{json.dumps(flags, ensure_ascii=False)}. Their cards are on screen. Explain the "
            "first one in one or two sentences and ask which value is right and why. Never "
            "pick a value yourself."
        )
    await turn(ui_event=note)


async def _flag_resolved(ctx: Ctx, send, payload: dict, turn) -> None:
    """The user answered a flag card. The phase may move (no blocking flag left -> ready)."""
    try:
        flag_id = str(FlagResolved.model_validate(payload).flag_id)
    except ValidationError:
        return await send(ErrorMsg(code="bad_message", message="bad flag_resolved payload"))
    flag = await asyncio.to_thread(repo.get_flag, ctx.db, ctx.user_id, flag_id)
    if not flag or flag["session_id"] != ctx.session["id"] or flag["status"] == "open":
        return await send(ErrorMsg(code="flag_not_resolved", message="flag not found or open"))
    left = await asyncio.to_thread(repo.list_flags, ctx.db, ctx.user_id, ctx.session["id"], "open")
    what = "picked a value" if flag["status"] == "resolved" else "acknowledged it"
    await turn(
        ui_event=f"The user {what} for the flag about {flag_summary(flag)['field']}. Open flags "
        f"left: {json.dumps([flag_summary(f) for f in left], ensure_ascii=False)}. Thank them in a "
        "few words; if a flag is left, explain the next one (its card is on screen)."
    )


async def _screen_share_started(ctx: Ctx, send) -> None:
    """ready -> form_fill, in code. Guided filling starts only once nothing blocks the form."""
    await sync_phase(ctx, send)  # a blocking flag may have opened since
    phase = ctx.session["phase"]
    if phase == "form_fill":
        return
    if phase != "ready":
        return await send(
            ErrorMsg(code="not_ready", message="finish checking your documents in the chat first")
        )
    row = await asyncio.to_thread(
        repo.update_session, ctx.db, ctx.user_id, ctx.session["id"], {"phase": "form_fill"}
    )
    ctx.session.update(row or {"phase": "form_fill"})
    payload = {"from": "ready", "to": "form_fill"}
    await asyncio.to_thread(
        repo.write_audit, ctx.db, ctx.user_id, ctx.session["id"], "phase.changed", payload
    )
    await send(PhaseMsg(phase="form_fill"))
