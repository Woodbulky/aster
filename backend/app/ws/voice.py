"""WS /ws/session/{id}: the conversation channel (docs/API.md): text, voice in, sentence-streamed
voice out."""

import asyncio
import contextlib
import logging
import time
import uuid
from collections import deque
from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ValidationError

from app.agent.orchestrator import run_turn, sync_phase
from app.agent.tools import TOOLS, Ctx, run_tool
from app.config import Settings, get_settings
from app.db import supabase as repo
from app.deps import Db, user_from_token
from app.speech import router as speech
from app.speech.base import SpeechUnavailable
from app.speech.stream import Speaker
from app.ws.protocol import (
    AgentState,
    AudioEnd,
    AudioStart,
    ClientMsg,
    ErrorMsg,
    FormSelected,
    Hello,
    Interrupt,
    Ping,
    Pong,
    Ready,
    ToolEvent,
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
        voice_out = speaker_for(ctx.lang) if spoken else None
        await run_turn(s, ctx, send, assistant_name=name, speaker_factory=voice_out, **kw)

    async def voice_turn(audio: bytes, head: AudioStart) -> None:
        nonlocal spoken
        t0 = time.monotonic()
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

    # ponytail: per-connection limit; per-user across tabs if abuse shows up.
    recent: deque[float] = deque()
    pending: AudioStart | None = None  # audio_start seen, waiting for its binary frame
    audio: bytes | None = None
    try:
        while True:
            frame = await ws.receive()
            if frame["type"] == "websocket.disconnect":
                return
            now = time.monotonic()
            while recent and now - recent[0] > 60:
                recent.popleft()
            if len(recent) >= RATE_LIMIT:
                await send(ErrorMsg(code="rate_limited", message="too many messages, slow down"))
                continue
            recent.append(now)
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
                case UiEvent(name=event):
                    start(
                        lambda event=event: text_turn(ui_event=UI_EVENT_TEXT[event]), preempt=False
                    )
                case Hello():
                    pass  # already authenticated; reconnects open a new socket
    finally:
        if current and not current.done():
            current.cancel()


async def _form_selected(ctx: Ctx, send, payload: dict, turn) -> None:
    """A tap on a scheme card sets the form in code, without asking the LLM."""
    try:
        pick = FormSelected.model_validate(payload)
    except ValidationError:
        return await send(ErrorMsg(code="bad_message", message="bad form_selected payload"))
    label = TOOLS["set_form"].label
    await send(ToolEvent(name="set_form", status="started", label=label))
    res = await asyncio.to_thread(run_tool, ctx, "set_form", pick.model_dump(exclude_none=True))
    await send(ToolEvent(name="set_form", status="done" if res.ok else "failed", label=label))
    if not res.ok:
        return await send(ErrorMsg(code="form_not_set", message=res.error or "form not set"))
    await turn(ui_event=f"The user picked {res.data['portal']} from the suggestions card.")
