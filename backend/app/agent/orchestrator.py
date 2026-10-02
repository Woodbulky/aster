"""One user turn: context -> LLM (phase tools) -> up to 6 tool calls -> final reply (AGENT.md).
Phase changes are computed in code from DB state after every tool round."""

import asyncio
import json
import logging
import re
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
from app.ws.protocol import (
    AgentState,
    AssistantDelta,
    AssistantMessage,
    CardMsg,
    PhaseMsg,
    ToolEvent,
)

log = logging.getLogger(__name__)

Send = Callable[[BaseModel], Awaitable[None]]
MAX_TOOL_CALLS = 6
HISTORY = 12
TOOL_OUTPUT_CHARS = 3000
LANG_NAMES = {"mr": "Marathi", "hi": "Hindi", "en": "English"}
# Qwen sometimes slips a CJK character into Marathi (PROGRESS M2). Devanagari is U+0900-097F.
# A reply that tells the user to tap a card that was never created (seen live with Groq).
_CARD_CLAIM = re.compile(r"card|कार्ड", re.IGNORECASE)
NO_CARD_NUDGE = (
    "[system check] You told the user to check a card, but you did not call "
    "propose_profile_update this turn, so no card exists. Call it now with the values the user "
    "gave. If there are none, reply with one short sentence asking for the next field."
)
_CJK = re.compile(r"[⺀-㏿㐀-䶿一-鿿가-힯豈-﫿＀-￯]")


def strip_cjk(text: str) -> str:
    return _CJK.sub("", text)


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
) -> tuple[str, list[dict[str, Any]], str]:
    """Stream one completion: text deltas go to the client, tool calls are assembled by index
    (arguments may arrive whole or in pieces)."""
    text: list[str] = []
    calls: dict[int, dict[str, Any]] = {}
    provider = ""
    async for ch in chat_stream(s, msgs, tools=tools, temperature=0.3):
        provider = ch.provider
        if c := strip_cjk(ch.delta.get("content") or ""):
            text.append(c)
            await send(AssistantDelta(message_id=message_id, text=c))
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
) -> None:
    if user_text is not None:
        row = await _db(
            repo.add_message,
            ctx.db,
            ctx.user_id,
            ctx.session["id"],
            {"role": "user", "content": user_text, "lang": ctx.lang, "input_mode": "text"},
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
        *history,
    ]
    message_id = str(uuid.uuid4())
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
            text, tool_calls, provider = await _complete(s, msgs, tools or None, send, message_id)
            reply.append(text)
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
    if not text:  # e.g. the model only showed a card: nothing to say or store
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
    await send(AgentState(state="happy" if changed else "idle"))
