"""One user turn: context -> LLM (phase tools) -> up to 6 tool calls -> final reply (AGENT.md).
Phase changes are computed in code from DB state after every tool round."""

import asyncio
import json
import logging
import re
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import BaseModel

from app.agent import phases
from app.agent.prompts import read, t
from app.agent.tools import TOOLS, Ctx, ToolResult, run_tool, schemas
from app.agent.tools.profile import masked
from app.config import Settings
from app.db import supabase as repo
from app.llm.client import LLMUnavailable, chat_stream
from app.speech.stream import Speaker
from app.ws.protocol import (
    AgentState,
    AssistantDelta,
    AssistantMessage,
    CardMsg,
    PhaseMsg,
    ToolEvent,
    TurnMetrics,
)

log = logging.getLogger(__name__)

Send = Callable[[BaseModel], Awaitable[None]]
MAX_TOOL_CALLS = 6
# A short spoken reply is a few sentences; the cap stops a looping model (seen live with the 8B
# GPU model) from streaming and paying for TTS forever.
REPLY_MAX_TOKENS = 800
HISTORY = 12
TOOL_OUTPUT_CHARS = 3000
LANG_NAMES = {"mr": "Marathi", "hi": "Hindi", "en": "English"}
# Qwen sometimes slips a CJK character into Marathi (PROGRESS M2). Devanagari is U+0900-097F.
# A reply that tells the user to tap a card that was never created (seen live with Groq).
# "Confirm बटण दाबा" with no card was seen live with the 8B GPU model.
_CARD_CLAIM = re.compile(r"card|कार्ड|confirm|पुष्टी|पुष्टि", re.IGNORECASE)
NO_CARD_NUDGE = (
    "[system check] You told the user to check a card, but you did not call "
    "propose_profile_update this turn, so no card exists. Call it now with the values the user "
    "gave. If there are none, reply with one short sentence asking for the next field."
)
_CJK = re.compile(r"[⺀-㏿㐀-䶿一-鿿가-힯豈-﫿＀-￯]")


def strip_cjk(text: str) -> str:
    return _CJK.sub("", text)


def _ms(t: float | None, t0: float) -> int | None:
    return None if t is None else round((t - t0) * 1000)


async def _db(fn: Callable[..., Any], *a: Any, **kw: Any) -> Any:
    return await asyncio.to_thread(fn, *a, **kw)


async def sync_phase(ctx: Ctx, send: Send) -> bool:
    """Move the session to the phase its DB state calls for. True if it changed."""
    profile = await _db(repo.get_profile, ctx.db, ctx.user_id)
    new = phases.next_phase(ctx.session, profile)
    old = ctx.session["phase"]
    if new == old:
        return False
    row = await _db(repo.update_session, ctx.db, ctx.user_id, ctx.session["id"], {"phase": new})
    ctx.session.update(row or {"phase": new})
    await _db(
        repo.write_audit,
        ctx.db,
        ctx.user_id,
        ctx.session["id"],
        "phase.changed",
        {"from": old, "to": new},
    )
    await send(PhaseMsg(phase=new))
    return True


async def _system_prompt(ctx: Ctx, assistant_name: str) -> str:
    phase = ctx.session["phase"]
    profile = await _db(repo.get_profile, ctx.db, ctx.user_id)
    missing = phases.missing_core(profile)
    pending = await _db(repo.latest_pending_proposal, ctx.db, ctx.user_id, ctx.session["id"])
    state = [
        f"Saved profile (masked): {json.dumps(masked(profile), ensure_ascii=False, default=str)}",
        f"Session: portal={ctx.session.get('portal') or 'not chosen'}",
    ]
    if phase == "onboarding" and missing:
        state.append(f"Missing core fields: {missing}")
        state.append(f"Suggested next question: {t(ctx.lang, f'ask.{missing[0]}')}")
    if pending:
        state.append(f"Card waiting for the user to confirm: {json.dumps(pending['updates'])}")
    base = (
        read("system")
        .replace("{assistant_name}", assistant_name)
        .replace("{lang}", f"{LANG_NAMES[ctx.lang]} ({ctx.lang})")
        .replace("{phase}", phase)
        .replace("{phase_instructions}", read(f"phase_{phase}"))
    )
    return base + "\n\n## State\n" + "\n".join(state)


def _with_lang_note(history: list[dict[str, Any]], lang: str) -> list[dict[str, Any]]:
    """After a language switch the old-language history wins over the system prompt (seen live:
    toggle on Hindi, user speaking Marathi, reply in Marathi). A note inside the latest user turn,
    written in the target language (Marathi and Hindi share a script, so an English "reply in
    Hindi" still got Marathi), is what models follow. Request only, never stored."""
    note = f"\n\n{t(lang, 'reply_in')}"
    out = list(history)
    for i in range(len(out) - 1, -1, -1):
        if out[i]["role"] == "user":
            out[i] = {**out[i], "content": out[i]["content"] + note}
            break
    return out


def _history(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for r in rows:
        if r["role"] in ("user", "assistant") and r.get("content"):
            out.append({"role": r["role"], "content": r["content"]})
        elif r["role"] == "system" and r.get("input_mode") == "ui":
            out.append({"role": "user", "content": f"[UI event] {r['content']}"})
    return out


async def _complete(
    s: Settings,
    msgs: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
    send: Send,
    message_id: str,
    speaker: Speaker | None = None,
    marks: dict[str, float] | None = None,
) -> tuple[str, list[dict[str, Any]], str]:
    """Stream one completion: text deltas go to the client, tool calls are assembled by index
    (arguments may arrive whole or in pieces)."""
    text: list[str] = []
    calls: dict[int, dict[str, Any]] = {}
    provider = ""
    async for ch in chat_stream(s, msgs, tools=tools, temperature=0.3, max_tokens=REPLY_MAX_TOKENS):
        provider = ch.provider
        if c := strip_cjk(ch.delta.get("content") or ""):
            text.append(c)
            if marks is not None:
                marks.setdefault("first_token", time.monotonic())
            await send(AssistantDelta(message_id=message_id, text=c))
            if speaker:
                speaker.feed(c)
        for tc in ch.delta.get("tool_calls") or []:
            i = tc.get("index", len(calls))
            slot = calls.setdefault(i, {"id": None, "name": "", "arguments": ""})
            slot["id"] = slot["id"] or tc.get("id")
            fn = tc.get("function") or {}
            slot["name"] += fn.get("name") or ""
            args = fn.get("arguments") or ""
            slot["arguments"] += args if isinstance(args, str) else json.dumps(args)
    out = [{**c, "id": c["id"] or f"call_{i}"} for i, c in sorted(calls.items())]
    return "".join(text), out, provider


def _tool_content(res: ToolResult) -> str:
    body = res.model_dump(exclude={"card"}, exclude_none=True)
    if res.card:
        body["card_shown"] = res.card.kind
    return json.dumps(body, ensure_ascii=False, default=str)[:TOOL_OUTPUT_CHARS]


async def run_turn(
    s: Settings,
    ctx: Ctx,
    send: Send,
    *,
    assistant_name: str,
    user_text: str | None = None,
    ui_event: str | None = None,
    input_mode: str = "text",
    user_lang: str | None = None,
    speaker_factory: Callable[[str], Speaker] | None = None,
    t0: float | None = None,
    stt_ms: int | None = None,
    stt_provider: str | None = None,
) -> None:
    """ctx.lang is the reply language (the user's toggle). user_lang = the language the user
    actually spoke (STT), stored on their message. t0 = when the utterance ended (voice)."""
    if user_text is not None:
        row = await _db(
            repo.add_message,
            ctx.db,
            ctx.user_id,
            ctx.session["id"],
            {
                "role": "user",
                "content": user_text,
                "lang": user_lang or ctx.lang,
                "input_mode": input_mode,
            },
        )
        ctx.message_id = row["id"] if row else None
    if ui_event is not None:
        await _db(
            repo.add_message,
            ctx.db,
            ctx.user_id,
            ctx.session["id"],
            {"role": "system", "content": ui_event, "lang": ctx.lang, "input_mode": "ui"},
        )

    await send(AgentState(state="thinking"))
    changed = await sync_phase(ctx, send)
    history = _history(
        await _db(repo.list_messages, ctx.db, ctx.user_id, ctx.session["id"], HISTORY)
    )
    msgs: list[dict[str, Any]] = [
        {"role": "system", "content": await _system_prompt(ctx, assistant_name)},
        *_with_lang_note(history, ctx.lang),
    ]
    message_id = str(uuid.uuid4())
    speaker = speaker_factory(message_id) if speaker_factory else None
    marks: dict[str, float] = {}
    t0 = t0 if t0 is not None else time.monotonic()
    reply: list[str] = []
    provider = ""
    calls = 0
    failed = False
    card_sent = False
    nudged = False
    onboarding = ctx.session["phase"] == "onboarding"
    try:
        while True:
            tools = schemas(ctx.session["phase"]) if calls < MAX_TOOL_CALLS else None
            text, tool_calls, provider = await _complete(
                s, msgs, tools or None, send, message_id, speaker, marks
            )
            reply.append(text)
            if tool_calls and speaker:
                speaker.flush()
            if not tool_calls:
                if (
                    onboarding
                    and not nudged
                    and not card_sent
                    and _CARD_CLAIM.search(text)
                    and not await _db(
                        repo.latest_pending_proposal, ctx.db, ctx.user_id, ctx.session["id"]
                    )
                ):
                    nudged = True
                    msgs.append({"role": "assistant", "content": text})
                    msgs.append({"role": "user", "content": NO_CARD_NUDGE})
                    continue
                break
            msgs.append(
                {
                    "role": "assistant",
                    "content": text or None,
                    "tool_calls": [
                        {
                            "id": c["id"],
                            "type": "function",
                            "function": {"name": c["name"], "arguments": c["arguments"] or "{}"},
                        }
                        for c in tool_calls
                    ],
                }
            )
            for c in tool_calls:
                calls += 1
                label = TOOLS[c["name"]].label if c["name"] in TOOLS else c["name"]
                if calls > MAX_TOOL_CALLS:
                    res = ToolResult(
                        ok=False, error="tool limit reached; answer with what you have"
                    )
                else:
                    await send(ToolEvent(name=c["name"], status="started", label=label))
                    await send(AgentState(state="thinking", detail=label))
                    res = await _db(run_tool, ctx, c["name"], c["arguments"])
                    await send(
                        ToolEvent(
                            name=c["name"], status="done" if res.ok else "failed", label=label
                        )
                    )
                    if res.card:
                        card_sent = True
                        await send(CardMsg(**res.card.model_dump()))
                    await _db(
                        repo.add_message,
                        ctx.db,
                        ctx.user_id,
                        ctx.session["id"],
                        {
                            "role": "tool",
                            "tool_name": c["name"],
                            "tool_payload": {"args": c["arguments"], "result": res.model_dump()},
                            "lang": ctx.lang,
                        },
                    )
                msgs.append(
                    {"role": "tool", "tool_call_id": c["id"], "content": _tool_content(res)}
                )
            if await sync_phase(ctx, send):
                changed = True
                msgs[0] = {"role": "system", "content": await _system_prompt(ctx, assistant_name)}
    except asyncio.CancelledError:  # barge-in: ponytail: the interrupted reply is not stored
        if speaker:
            speaker.cancel()
        raise
    except LLMUnavailable as e:
        failed = True
        log.warning("llm unavailable: %s", e)
    except Exception:
        failed = True
        log.exception("turn failed mid-stream")

    text = "".join(reply).strip()
    if not text and failed:
        text = t(ctx.lang, "llm_unavailable") or ""
        provider = "template"
        await send(AssistantDelta(message_id=message_id, text=text))
        if speaker:
            speaker.feed(text)
    if not text:  # e.g. the model only showed a card: nothing to say or store
        if speaker:
            speaker.cancel()
        await send(AgentState(state="happy" if changed else "idle"))
        return
    await _db(
        repo.add_message,
        ctx.db,
        ctx.user_id,
        ctx.session["id"],
        {
            "id": message_id,
            "role": "assistant",
            "content": text,
            "lang": ctx.lang,
            "provider": provider,
        },
    )
    await send(AssistantMessage(message_id=message_id, text=text, lang=ctx.lang))  # type: ignore[arg-type]
    if speaker:
        try:
            await speaker.finish()
        except asyncio.CancelledError:
            speaker.cancel()
            raise
        m = TurnMetrics(
            stt_ms=stt_ms,
            stt_provider=stt_provider,
            llm_first_token_ms=_ms(marks.get("first_token"), t0),
            first_audio_ms=_ms(speaker.first_audio_at, t0),
        )
        log.info("turn_metrics %s", m.model_dump_json(exclude={"type"}))  # timings only
        await send(m)
    await send(AgentState(state="happy" if changed else "idle"))
