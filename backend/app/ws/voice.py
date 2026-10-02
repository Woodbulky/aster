"""WS /ws/session/{id}: the conversation channel (docs/API.md). Text only until M4 adds audio."""

import asyncio
import time
import uuid
from collections import deque
from typing import Annotated

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ValidationError

from app.agent.orchestrator import run_turn, sync_phase
from app.agent.tools import TOOLS, Ctx, run_tool
from app.config import Settings, get_settings
from app.db import supabase as repo
from app.deps import Db, user_from_token
from app.ws.protocol import (
    ClientMsg,
    ErrorMsg,
    FormSelected,
    Hello,
    Ping,
    Pong,
    Ready,
    ToolEvent,
    UiEvent,
    UserText,
)

router = APIRouter()

HELLO_TIMEOUT_S = 10.0
RATE_LIMIT = 30  # messages per minute (ARCHITECTURE "Security")
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
    async def send(m: BaseModel) -> None:
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

    async def turn(**kw: str) -> None:
        await run_turn(s, ctx, send, assistant_name=name, **kw)

    if not await asyncio.to_thread(repo.list_messages, db, user_id, ctx.session["id"], 1):
        await turn(ui_event="Conversation started. Greet the user warmly and begin your goal.")

    # ponytail: per-connection limit; per-user across tabs if abuse shows up.
    recent: deque[float] = deque()
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
        try:
            msg = ClientMsg.validate_json(frame.get("text") or "")
        except ValidationError:
            await send(ErrorMsg(code="bad_message", message="unsupported message"))
            continue
        match msg:
            case Ping():
                await send(Pong())
            case UserText(text=text):
                await turn(user_text=text)
            case UiEvent(name="form_selected", payload=payload):
                await _form_selected(ctx, send, payload, turn)
            case UiEvent(name=event):
                await turn(ui_event=UI_EVENT_TEXT[event])
            case Hello():
                pass  # already authenticated; reconnects open a new socket


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
