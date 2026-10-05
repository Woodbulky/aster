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
from app.agent.answers import read_answers
from app.agent.prompts import read, t
from app.agent.tools import TOOLS, Card, Ctx, ToolResult, run_tool, schemas
from app.agent.tools.forms import pack_for_name
from app.agent.tools.profile import masked
from app.config import Settings, get_settings
from app.db import supabase as repo
from app.llm.client import LLMUnavailable, chat_stream
from app.research.packs import usable_packs
from app.speech.stream import Speaker
from app.verify.checks import flag_summary, propose_profile_update, reread_after
from app.verify.pipeline import process_document
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
MAX_RESEARCH_NUDGES = 2
# Read-only: same args -> same answer within a turn, and safe to run side by side.
LOOKUPS = {"research_scheme", "search_web", "fetch_url", "read_pdf"}
READS = {"research_scheme", "fetch_url", "read_pdf"}  # tools that hand the model page text
TOOL_LIMIT = "tool limit reached; answer with what you have"
REPEAT_CALL = (
    "you already made this exact call this turn; use that result, change the query, "
    "or answer with what you have"
)
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
# Seen live (8B GPU model): it read the pages, then typed its own list of "official rules"
# instead of calling save_research, so nothing was quote-checked.
RESEARCH_NUDGE = (
    "[system check] You read pages but did not call save_research, so nothing you wrote was "
    "checked and the user has not seen it. Call save_research now with the rules and documents, "
    "each with a quote copied exactly from the page text. Do not list rules in your reply. If "
    "the pages have no rules, say so in one sentence."
)
# Qwen's own tool-call syntax, typed out as text when no tools were offered (seen live on Groq
# after the tool cap). Never shown, spoken or stored.
_TOOL_MARKUP = re.compile(r"<tool_call>.*?(?:</tool_call>|$)", re.DOTALL)
# Seen live (GPU and Groq): the history keeps only reply text, not the tool calls behind it, so
# after a few turns the model copies "Let me check… Let me read…" and calls nothing.
NO_TOOL_NUDGE = (
    "[system check] You said what you would do but called no tool, so nothing happened and the "
    "user has not seen your text. Call the next tool now. If the user named a different "
    "scholarship, call set_form with it first. Otherwise: get_knowledge_pack if the state has a "
    "scheme_key; else research_scheme, or save_research on the pages you already read. Do not "
    "announce it; just call it."
)
_CJK = re.compile(r"[⺀-㏿㐀-䶿一-鿿가-힯豈-﫿＀-￯]")


# "ठीक है, अब से मैं केवल हिंदी में ही जवाब दूँगा।" — models answered the language note itself,
# every turn, then copied that line from the history (seen live). Sentences with all three parts
# are removed from the history the model sees and from the stored reply.
_ACK_PARTS = (
    re.compile(r"केवल|सिर्फ|फक्त|\bonly\b", re.IGNORECASE),
    re.compile(r"हिंदी|हिन्दी|मराठी|english|hindi|marathi", re.IGNORECASE),
    re.compile(r"जवाब|उत्तर|बोल|repl|respond|answer|speak", re.IGNORECASE),
)


def _sentences(text: str) -> list[str]:
    return re.split(r"(?<=[।.!?\n])", text)


def strip_lang_ack(text: str) -> str:
    parts = _sentences(text)
    return "".join(s for s in parts if not all(p.search(s) for p in _ACK_PARTS)).strip()


# "Let me check the official rules…" with no tool call behind it (seen live on GPU and Groq, in
# research and eligibility). The model copies it from its own earlier replies.
_PROMISE = re.compile(
    r"^\s*(let me|let's|i'll|i will|i am going to|i'm going to|one moment|please wait)\b"
    r"|(देखती|देखता|जाँचती|जाँचता|पाहते|पाहतो|तपासते|तपासतो)\s*(हूँ|हूं|आहे)?\s*[।.]?\s*$",
    re.IGNORECASE,
)


def promise_only(text: str) -> bool:
    parts = [s for s in _sentences(text) if s.strip()]
    return bool(parts) and all(_PROMISE.search(s) for s in parts)


def strip_promises(text: str) -> str:
    return "".join(s for s in _sentences(text) if not _PROMISE.search(s)).strip()


def strip_markup(text: str) -> str:
    return _TOOL_MARKUP.sub("", text)


def strip_cjk(text: str) -> str:
    return _CJK.sub("", text)


def _ms(t: float | None, t0: float) -> int | None:
    return None if t is None else round((t - t0) * 1000)


async def _db(fn: Callable[..., Any], *a: Any, **kw: Any) -> Any:
    return await asyncio.to_thread(fn, *a, **kw)


async def _none() -> None:
    return None


async def sync_phase(ctx: Ctx, send: Send) -> bool:
    """Move the session to the phase its DB state calls for. True if it changed. next_phase moves
    one step, so this repeats until it settles: a scheme whose research was reused from another
    student goes choose_form -> research -> eligibility in one go."""
    changed = False
    for _ in range(3):  # at most choose_form -> research -> eligibility
        if not await _sync_once(ctx, send):
            break
        changed = True
    return changed


async def _sync_once(ctx: Ctx, send: Send) -> bool:
    scheme = phases.scheme_of(ctx.session)
    sid, phase = ctx.session["id"], ctx.session["phase"]
    profile, research, flags = await asyncio.gather(  # side by side, not one after another
        _db(repo.get_profile, ctx.db, ctx.user_id),
        _db(repo.latest_research, ctx.db, ctx.user_id, sid, scheme)
        if scheme and phase in ("research", "eligibility")
        else _none(),
        _db(repo.list_flags, ctx.db, ctx.user_id, sid, "open")
        if phase in ("verification", "ready")
        else _none(),
    )
    researched = bool(research)
    blocks = sum(f["severity"] == "block" for f in flags or [])
    new = phases.next_phase(ctx.session, profile, researched, blocks)
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
    if new == "ready":  # the readiness card comes from code, not from the model's judgement
        await run_tool_ui(ctx, send, "readiness_summary", {})
    return True


def _scheme_line(session: dict[str, Any]) -> str:
    if session.get("scheme_key"):
        return f"{session.get('scheme_name') or ''} (scheme_key={session['scheme_key']})"
    if session.get("scheme_name"):
        return f"{session['scheme_name']} (no knowledge pack: research it live)"
    return "not chosen"


async def _system_prompt(ctx: Ctx, assistant_name: str) -> str:
    phase = ctx.session["phase"]
    sid = ctx.session["id"]
    flag_phase = phase in ("documents", "verification", "ready")
    # One round trip for everything the prompt needs (they were ~4 calls in a row).
    profile, pending, flags, read_pages = await asyncio.gather(
        _db(repo.get_profile, ctx.db, ctx.user_id),
        _db(repo.latest_pending_proposal, ctx.db, ctx.user_id, sid),
        _db(repo.list_flags, ctx.db, ctx.user_id, sid, "open") if flag_phase else _none(),
        _db(repo.list_fetched, ctx.db, ctx.user_id, sid) if phase == "research" else _none(),
    )
    missing = phases.missing_core(profile)
    state = [
        f"Saved profile (masked): {json.dumps(masked(profile), ensure_ascii=False, default=str)}",
        f"Chosen scholarship: {_scheme_line(ctx.session)}",
    ]
    if pack := usable_packs().get(ctx.session.get("scheme_key") or ""):
        # The history keeps reply text only: without this, a question about the scheme (amount,
        # test, helpline) after the research step had no facts to answer from.
        facts = {
            "summary": pack.summary.get(ctx.lang),
            "deadlines": {
                d.label.get(ctx.lang): d.date and d.date.isoformat() for d in pack.deadlines
            },
            "notes": pack.notes,
            "official_urls": pack.official_urls,
        }
        state.append(
            "Official facts about the chosen scholarship (reviewed knowledge pack, like a tool "
            "result; answer questions about it from these, say you don't know the rest): "
            + json.dumps(facts, ensure_ascii=False)
        )
    if phase == "onboarding" and missing:
        state.append(f"Missing core fields: {missing}")
        state.append(f"Suggested next question: {t(ctx.lang, f'ask.{missing[0]}')}")
    if pending:
        # masked: a proposal from a resolved caste flag must not hand the model the value
        waiting = json.dumps(masked(pending["updates"]), ensure_ascii=False)
        state.append(f"Card waiting for the user to confirm: {waiting}")
    if read_pages:
        # The tool calls are not in the history: without this the model searched again for pages
        # it had read in an earlier turn.
        pages = [{"url": p["url"], "content_id": p["id"]} for p in read_pages[-6:]]
        state.append(
            "Pages already read this session (use their content_id in save_research): "
            + json.dumps(pages, ensure_ascii=False)
        )
    if flag_phase:
        # The model invented problems that were never flagged (seen live: a "father's name"
        # mismatch, then the same reply on a loop). It only gets the real list.
        open_ = json.dumps([flag_summary(f) for f in flags], ensure_ascii=False)
        state.append(f"Open flags (the only problems; their cards are on screen): {open_}")
        # Seen live: "You're good to go!" with a blocking flag still open.
        blocks = sum(f["severity"] == "block" for f in flags)
        if phase == "documents":
            # Seen live: no open flags here read as "your form is ready" (even "already filled"),
            # though the documents were never checked together.
            state.append(
                "Form ready: NO (the documents are not checked together yet: run_verification "
                "does that when the user is done uploading or wants to fill the form)."
            )
        else:
            state.append(
                f"Form ready: {'NO' if blocks else 'yes'} ({blocks} blocking flag(s) open)."
            )
        state.append(
            "Never say the documents or the form are ready while this says NO. Aster never fills "
            "the portal: never say the form is filled or submitted."
        )
    base = (
        read("system")
        .replace("{assistant_name}", assistant_name)
        .replace("{lang}", f"{LANG_NAMES[ctx.lang]} ({ctx.lang})")
        .replace("{phase}", phase)
        .replace("{phase_instructions}", read(f"phase_{phase}"))
    )
    return base + "\n\n## State\n" + "\n".join(state)


def _with_lang_note(
    history: list[dict[str, Any]], rows: list[dict[str, Any]], lang: str
) -> list[dict[str, Any]]:
    """After a language switch the old-language history wins over the system prompt (seen live:
    toggle on Hindi, user speaking Marathi, reply in Marathi). A note inside the latest user turn,
    written in the target language (Marathi and Hindi share a script, so an English "reply in
    Hindi" still got Marathi), is what models follow. Only added while the recent history has
    another language, and worded as a silent instruction: a request ("please reply only in Hindi
    from now on") was acknowledged on every turn. Request only, never stored."""
    talk = [r for r in rows if r["role"] in ("user", "assistant")]
    if not any(r.get("lang") not in (None, lang) for r in talk):
        return history
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
            text = r["content"]
            if r["role"] == "assistant":  # drop what the model would otherwise copy
                text = strip_promises(strip_lang_ack(text))
            if text:
                out.append({"role": r["role"], "content": text})
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
    # Conversation goes to settings.brain_primary first (Groq ~2 s vs ~5 s on the T4); document
    # calls keep LLM_PRIMARY's order (they pass sensitive_kind, never through here).
    async for ch in chat_stream(
        s,
        msgs,
        tools=tools,
        prefer=s.brain_primary,
        temperature=0.3,
        max_tokens=REPLY_MAX_TOKENS,
    ):
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


async def run_tool_ui(
    ctx: Ctx, send: Send, name: str, raw_args: str | dict[str, Any]
) -> ToolResult:
    """Run a tool with its UI events, send its card, store it (the history keeps the card, so the
    client can show it again after a reload). Used by the LLM loop and by card taps."""
    label = TOOLS[name].label if name in TOOLS else name
    await send(ToolEvent(name=name, status="started", label=label))
    await send(AgentState(state="thinking", detail=label))
    phase = ctx.session["phase"]
    res = await _db(run_tool, ctx, name, raw_args)
    await send(ToolEvent(name=name, status="done" if res.ok else "failed", label=label))
    if ctx.session["phase"] != phase:  # a tool that moves the phase itself (request_documents)
        await send(PhaseMsg(phase=ctx.session["phase"]))
    if res.card:
        await send(CardMsg(**res.card.model_dump()))
    args = raw_args if isinstance(raw_args, str) else json.dumps(raw_args, ensure_ascii=False)
    await _db(
        repo.add_message,
        ctx.db,
        ctx.user_id,
        ctx.session["id"],
        {
            "role": "tool",
            "tool_name": name,
            "tool_payload": {"args": args, "result": res.model_dump()},
            "lang": ctx.lang,
        },
    )
    if name == "resolve_flag" and res.ok:
        flag_id = json.loads(args)["flag_id"]
        await offer_profile_update(ctx, send, flag_id)
        await reread_document(ctx, flag_id)
    return res


_rereads: set[asyncio.Task] = set()  # keep a reference: the loop holds tasks only weakly


async def reread_document(ctx: Ctx, flag_id: str) -> None:
    """Answered in words that the document IS right: read it again in the background (the open
    conversation hears when it is done, like any upload)."""
    flag = await _db(repo.get_flag, ctx.db, ctx.user_id, flag_id)
    if flag and (doc_id := reread_after(flag)):
        job = process_document(get_settings(), ctx.user_id, ctx.session["id"], doc_id)
        task = asyncio.create_task(job)
        _rereads.add(task)
        task.add_done_callback(_rereads.discard)


async def offer_profile_update(ctx: Ctx, send: Send, flag_id: str) -> None:
    """A resolved flag on a profile field -> a confirm_profile card in code, so the profile can
    follow the value the user picked (guardrail 4: saved only when they confirm the card)."""
    flag = await _db(repo.get_flag, ctx.db, ctx.user_id, flag_id)
    prop = flag and await _db(propose_profile_update, ctx.db, ctx.user_id, flag)
    if not prop:
        return
    payload = {"proposal_id": prop["id"], "updates": prop["updates"]}
    card = Card(kind="confirm_profile", payload=payload)
    await send(CardMsg(**card.model_dump()))
    res = ToolResult(ok=True, data={"proposal_id": prop["id"], "from_flag": flag_id}, card=card)
    await _db(  # stored like a tool row, so the card comes back after a reload
        repo.add_message,
        ctx.db,
        ctx.user_id,
        ctx.session["id"],
        {
            "role": "tool",
            "tool_name": "propose_profile_update",
            "tool_payload": {"args": json.dumps(prop["updates"]), "result": res.model_dump()},
            "lang": ctx.lang,
        },
    )


async def show_new_flag_cards(ctx: Ctx, send: Send) -> list[dict[str, Any]]:
    """A card for every open flag whose card was not shown yet, in code: the model was seen
    talking about flags without ever showing their cards. -> their summaries."""
    shown = await _db(repo.shown_flag_ids, ctx.db, ctx.user_id, ctx.session["id"])
    flags = await _db(repo.list_flags, ctx.db, ctx.user_id, ctx.session["id"], "open")
    out = []
    for f in flags:
        if f["id"] not in shown:
            res = await run_tool_ui(ctx, send, "ask_resolution", {"flag_id": f["id"]})
            if res.ok:
                out.append(res.data)
    return out


FLAG_PHASES = ("documents", "verification", "ready")


async def _apply_answers(s: Settings, ctx: Ctx, send: Send, user_text: str) -> bool:
    """Save the flags the user just answered in words (answers.py). The model's reply then only
    confirms; it is told what was saved. -> True if anything was saved."""
    flags = await _db(repo.list_flags, ctx.db, ctx.user_id, ctx.session["id"], "open")
    if not flags:
        return False
    recent = await _db(repo.list_messages, ctx.db, ctx.user_id, ctx.session["id"], 4)
    asked = next((r["content"] for r in reversed(recent) if r["role"] == "assistant"), "") or ""
    answers = await read_answers(s, flags, user_text, asked, ctx.user_id, ctx.session["id"])
    saved = []
    for a in answers:
        if not a.reason or not (a.choice or a.new_value or a.keep_as_is):
            continue  # no reason given: the reply asks why
        args = {"flag_id": a.flag_id, "reason": a.reason}
        if not a.keep_as_is:  # "keep it as is" = acknowledge, not a pick
            args |= {"choice": a.choice} if a.choice else {}
            args |= {"new_value": a.new_value} if a.new_value and not a.choice else {}
        res = await run_tool_ui(ctx, send, "resolve_flag", args)
        if res.ok:
            saved.append(res.data)
    if saved:
        note = (
            f"Saved from the user's {ctx.input_mode} answer: "
            f"{json.dumps(saved, ensure_ascii=False)}. Confirm it in a few words, then go on."
        )
        await _db(
            repo.add_message,
            ctx.db,
            ctx.user_id,
            ctx.session["id"],
            {"role": "system", "content": note, "lang": ctx.lang, "input_mode": "ui"},
        )
    return bool(saved)


# "I'm done uploading", "check everything", "सगळं तपासा", "सब जाँच लो", "let's fill the form":
# run the checks in code (filling starts from ready, after them).
_DONE_UPLOADING = re.compile(
    r"\b(done|finished|that'?s all|check (it )?(all|everything))\b|झाले|झालं|संपल|सगळं तपास|सर्व तपास"
    r"|हो गया|हो गए|सब (जाँच|जांच|चेक)"
    r"|\b(fill(ing)? (the |my )?form|form fill(ing)?|start filling)\b|फॉर्म भर",
    re.IGNORECASE,
)


def _as_tool_call(name: str, args: dict[str, Any], res: ToolResult) -> list[dict[str, Any]]:
    """A tool run by code, written into the request like the model's own call."""
    cid = f"code_{name}"
    call = {
        "id": cid,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(args)},
    }
    return [
        {"role": "assistant", "content": None, "tool_calls": [call]},
        {"role": "tool", "tool_call_id": cid, "content": _tool_content(res)},
    ]


async def _fast_path(ctx: Ctx, send: Send, user_text: str) -> list[dict[str, Any]]:
    """Obvious intents run in code before the LLM (one round fewer, and no wrong pick): a scheme
    named clearly in choose_form, or "I'm done uploading" in documents. -> the tool messages."""
    phase = ctx.session["phase"]
    out: list[dict[str, Any]] = []
    if phase == "choose_form" and (key := pack_for_name(user_text)):
        res = await run_tool_ui(ctx, send, "set_form", {"scheme_key": key})
        out += _as_tool_call("set_form", {"scheme_key": key}, res)
        if res.ok:  # a pack scheme: its verified rules load at once too
            await sync_phase(ctx, send)
            pack = await run_tool_ui(ctx, send, "get_knowledge_pack", {})
            out += _as_tool_call("get_knowledge_pack", {}, pack)
    elif (
        phase in ("documents", "verification")
        and len(user_text.split()) <= 8
        and _DONE_UPLOADING.search(user_text)
    ):
        res = await run_tool_ui(ctx, send, "run_verification", {})
        out += _as_tool_call("run_verification", {}, res)
        if res.ok:
            await show_new_flag_cards(ctx, send)
    return out


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
    await send(AgentState(state="thinking"))  # first: the avatar reacts before any DB call
    rows: list[dict[str, Any]] = []
    if user_text is not None:
        rows.append(
            {
                "role": "user",
                "content": user_text,
                "lang": user_lang or ctx.lang,
                "input_mode": input_mode,
            }
        )
        ctx.input_mode = input_mode
        ctx.user_text = user_text
    if ui_event is not None:
        if user_text is None:
            ctx.input_mode = "ui"  # a tap is not the user's words: resolve_flag refuses it
        rows.append({"role": "system", "content": ui_event, "lang": ctx.lang, "input_mode": "ui"})

    async def store() -> None:
        for r in rows:  # in order: the history reads them back by created_at
            row = await _db(repo.add_message, ctx.db, ctx.user_id, ctx.session["id"], r)
            if r["role"] == "user":
                ctx.message_id = row["id"] if row else None

    # The messages are written while the phase syncs (independent; one round trip saved).
    _, changed = await asyncio.gather(store(), sync_phase(ctx, send))
    if user_text is not None and ctx.session["phase"] in FLAG_PHASES:
        if await _apply_answers(s, ctx, send, user_text):
            changed = await sync_phase(ctx, send) or changed
    done_in_code: list[dict[str, Any]] = []
    if user_text is not None:
        done_in_code = await _fast_path(ctx, send, user_text)
        if done_in_code:
            changed = await sync_phase(ctx, send) or changed
    rows, system = await asyncio.gather(
        _db(repo.list_messages, ctx.db, ctx.user_id, ctx.session["id"], HISTORY),
        _system_prompt(ctx, assistant_name),
    )
    msgs: list[dict[str, Any]] = [
        {"role": "system", "content": system},
        *_with_lang_note(_history(rows), rows, ctx.lang),
        *done_in_code,  # the model sees what code already did this turn, as its own tool calls
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
    read_pages = saved = False
    save_bonus = False  # one save_research past the cap, so found quotes aren't lost
    research_nudges = 0
    promised = False
    checked = False  # check_eligibility ran in code after save_research
    seen: set[tuple[str, str]] = set()  # (tool, args) already run this turn
    onboarding = ctx.session["phase"] == "onboarding"

    async def hold(_m: BaseModel) -> None:
        pass

    try:
        while True:
            tools = schemas(ctx.session["phase"]) if calls < MAX_TOOL_CALLS else None
            if save_bonus:
                tools = [t for t in schemas("research") if t["function"]["name"] == "save_research"]
            # Research replies are held until the round is checked, so rules the model typed
            # without save_research never reach the user (guardrail 2: no source, no value).
            held = ctx.session["phase"] == "research"
            text, tool_calls, provider = await _complete(
                s,
                msgs,
                tools or None,
                hold if held else send,
                message_id,
                None if held else speaker,
                marks,
            )
            # Research isn't done until save_research: a reply that stops before that (narration
            # copied from the history, seen live even after a search) is held and nudged.
            if (
                held
                and not tool_calls
                and not saved
                and research_nudges < MAX_RESEARCH_NUDGES
                and (calls < MAX_TOOL_CALLS or read_pages)
            ):
                research_nudges += 1
                save_bonus = calls >= MAX_TOOL_CALLS
                msgs.append({"role": "assistant", "content": text})
                msgs.append(
                    {"role": "user", "content": RESEARCH_NUDGE if read_pages else NO_TOOL_NUDGE}
                )
                continue
            # Any other phase: a reply that only promises to act, with no tool call. Already
            # streamed, so the final message (which replaces it in the UI) drops it.
            if (
                not held
                and not tool_calls
                and not onboarding
                and not promised
                and calls < MAX_TOOL_CALLS
                and promise_only(text)
            ):
                promised = True
                msgs.append({"role": "assistant", "content": text})
                msgs.append({"role": "user", "content": NO_TOOL_NUDGE})
                continue
            text = strip_markup(text)
            if held and text:
                await send(AssistantDelta(message_id=message_id, text=text))
                if speaker:
                    speaker.feed(text)
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
            # Every call is checked first, in order (the cap, repeats); then the ones to run.
            todo: list[tuple[dict[str, Any], ToolResult | None]] = []
            for c in tool_calls:
                calls += 1
                bonus = save_bonus and c["name"] == "save_research"
                save_bonus = save_bonus and not bonus
                key = (c["name"], c["arguments"] or "{}")
                if calls > MAX_TOOL_CALLS and not bonus:
                    todo.append((c, ToolResult(ok=False, error=TOOL_LIMIT)))
                elif key in seen and c["name"] in LOOKUPS:
                    # Seen live: the same search_web 5× in one turn, then the LLM call failed.
                    todo.append((c, ToolResult(ok=False, error=REPEAT_CALL)))
                else:
                    seen.add(key)
                    todo.append((c, None))
            run = [c for c, res in todo if res is None]
            ran: dict[str, ToolResult] = {}
            if len(run) > 1 and all(c["name"] in LOOKUPS for c in run):
                # Read-only lookups side by side: three pages take as long as the slowest one.
                done = await asyncio.gather(
                    *(run_tool_ui(ctx, send, c["name"], c["arguments"]) for c in run)
                )
                ran = {c["id"]: res for c, res in zip(run, done, strict=True)}
            for c, res in todo:
                if res is None:
                    res = ran.get(c["id"]) or await run_tool_ui(
                        ctx, send, c["name"], c["arguments"]
                    )
                    card_sent = card_sent or res.card is not None
                    read_pages = read_pages or (res.ok and c["name"] in READS)
                    saved = saved or (res.ok and c["name"] == "save_research")
                msgs.append(
                    {"role": "tool", "tool_call_id": c["id"], "content": _tool_content(res)}
                )
                if c["name"] == "run_verification" and res.ok:
                    card_sent = bool(await show_new_flag_cards(ctx, send)) or card_sent
            if await sync_phase(ctx, send):
                changed = True
                msgs[0] = {"role": "system", "content": await _system_prompt(ctx, assistant_name)}
                if saved and ctx.session["phase"] == "eligibility" and not checked:
                    # The card and its counts come from code, not from the model (seen live: it
                    # skipped check_eligibility and recited "3 of 5 met" from the prompt example).
                    checked = True
                    res = await run_tool_ui(ctx, send, "check_eligibility", {})
                    card_sent = card_sent or res.card is not None
                    msgs.append(
                        {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "auto_check",
                                    "type": "function",
                                    "function": {"name": "check_eligibility", "arguments": "{}"},
                                }
                            ],
                        }
                    )
                    msgs.append(
                        {
                            "role": "tool",
                            "tool_call_id": "auto_check",
                            "content": _tool_content(res),
                        }
                    )
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

    text = strip_lang_ack(strip_markup("".join(reply)))
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
