"""Verification tools (AGENT.md): run the cross-source checks, list flags, show a flag's card."""

from pydantic import BaseModel, ConfigDict, Field
from rapidfuzz import fuzz

from app.agent.tools import Card, Ctx, ToolResult, register
from app.db import supabase as repo
from app.verify.checks import (
    ResolveError,
    flag_card,
    flag_summary,
    readiness,
    resolve,
    run_checks,
)
from app.verify.contradictions import same
from app.verify.validator import norm, numbers


class NoArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


@register(
    "run_verification",
    "Check all uploaded documents against each other and the profile, including required "
    "documents that are missing. Call it when the user says they have uploaded everything.",
    "Checking your documents against each other",
    NoArgs,
)
def run_verification(ctx: Ctx, _: NoArgs) -> ToolResult:
    run_checks(ctx.db, ctx.user_id, ctx.session, include_missing=True)
    if ctx.session["phase"] == "documents":
        row = repo.update_session(ctx.db, ctx.user_id, ctx.session["id"], {"phase": "verification"})
        ctx.session.update(row or {"phase": "verification"})
        payload = {"from": "documents", "to": "verification"}
        repo.write_audit(ctx.db, ctx.user_id, ctx.session["id"], "phase.changed", payload)
    open_ = repo.list_flags(ctx.db, ctx.user_id, ctx.session["id"], "open")
    return ToolResult(
        ok=True,
        data={
            "open_flags": [flag_summary(f) for f in open_],
            "rule": "If there are open flags, call ask_resolution for the first one and explain "
            "it in one or two sentences. Never resolve a flag yourself.",
        },
    )


class StatusArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str | None = Field(default="open", description="open | resolved | acknowledged")


@register(
    "list_flags",
    "List the problems found in the user's documents (open by default).",
    "Checking what needs your attention",
    StatusArgs,
)
def list_flags(ctx: Ctx, args: StatusArgs) -> ToolResult:
    flags = repo.list_flags(ctx.db, ctx.user_id, ctx.session["id"], args.status)
    return ToolResult(ok=True, data=[flag_summary(f) for f in flags])


class FlagArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    flag_id: str


@register(
    "ask_resolution",
    "Show the card for one flag so the user can pick the right value (or acknowledge it) with a "
    "reason.",
    "Showing what needs your attention",
    FlagArgs,
)
def ask_resolution(ctx: Ctx, args: FlagArgs) -> ToolResult:
    flag = repo.get_flag(ctx.db, ctx.user_id, args.flag_id)
    if not flag or flag["session_id"] != ctx.session["id"]:
        return ToolResult(ok=False, error="no such flag in this session")
    kind, payload = flag_card(flag, ctx.lang)
    return ToolResult(ok=True, data=flag_summary(flag), card=Card(kind=kind, payload=payload))


REASON_FROM_USER = 70  # partial_ratio of the reason against the user's message


def _said(value: str, text: str) -> bool:
    """The value is in the user's words: as text, or as the same number ("2025", "1,48,000")."""
    if norm(value) in norm(text):
        return True
    v = numbers(value)
    return len(v) == 1 and any(abs(v[0] - n) <= 0.01 for n in numbers(text))


class ResolveArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    flag_id: str
    choice: str | None = Field(
        default=None,
        description="the value the user chose, exactly as one of the flag's values (e.g. 148000)",
    )
    new_value: str | None = Field(
        default=None, max_length=200, description="a different value the user stated, if any"
    )
    reason: str = Field(min_length=3, max_length=300, description="the user's reason, their words")


@register(
    "resolve_flag",
    "Record the user's answer to a flag from what they just said: the value they chose (choice) "
    "or a new value they stated (new_value), with their reason. Neither = they keep it as is. "
    "Only call it when the user clearly said which value is right; if they gave no reason, ask "
    "why first.",
    "Saving your answer",
    ResolveArgs,
)
def resolve_flag(ctx: Ctx, args: ResolveArgs) -> ToolResult:
    """Guardrail 3: the user decides; the model only maps their words to a candidate. The
    evidence (message id, voice/text) is set by the orchestrator, never by the model."""
    if not ctx.message_id or ctx.input_mode not in ("voice", "text"):
        return ToolResult(ok=False, error="only the user's own words can answer a flag; ask them")
    if fuzz.partial_ratio(norm(args.reason), norm(ctx.user_text)) < REASON_FROM_USER:
        return ToolResult(ok=False, error="the reason must be the user's own words; ask them why")
    flag = repo.get_flag(ctx.db, ctx.user_id, args.flag_id)
    if not flag or flag["session_id"] != ctx.session["id"]:
        return ToolResult(ok=False, error="no such flag in this session")
    candidate_id = None
    value = args.new_value
    if value and not _said(value, ctx.user_text):
        # Guardrail 2 (found by /guardrails): a typed value's source is the user's message, so it
        # must be in it, not something the model inferred.
        return ToolResult(ok=False, error="new_value must be what the user said; ask them")
    if args.choice:
        cands = flag["details"].get("candidates", [])
        hits = [c for c in cands if same(c["field_key"], c["value"], args.choice)]
        if len(hits) == 1:
            candidate_id = hits[0]["id"]
        elif not value:
            options = sorted({c["value"] for c in cands})
            return ToolResult(ok=False, error=f"choice must be one of {options}, or use new_value")
    try:
        out = resolve(
            ctx.db,
            ctx.user_id,
            ctx.session["id"],
            args.flag_id,
            reason=args.reason,
            via="voice" if ctx.input_mode == "voice" else "text",
            candidate_id=candidate_id,
            value=None if candidate_id else value,
            message_id=ctx.message_id,
        )
    except ResolveError as e:
        return ToolResult(ok=False, error=str(e))
    kind, payload = flag_card(out, ctx.lang)  # the card shows the answer
    return ToolResult(ok=True, data=flag_summary(out), card=Card(kind=kind, payload=payload))


@register(
    "readiness_summary",
    "Show the readiness card: every value the form will use with its source, and any problem "
    "that still blocks the form.",
    "Checking if everything is ready",
    NoArgs,
)
def readiness_summary(ctx: Ctx, _: NoArgs) -> ToolResult:
    payload = readiness(ctx.db, ctx.user_id, ctx.session)
    data = {
        "ready": payload["ready"],
        "blocking": payload["open_block"],
        "warnings": len(payload["open_warn"]),
        "kept_as_is": len(payload["acknowledged"]),
        "values": len(payload["fields"]),
    }
    return ToolResult(ok=True, data=data, card=Card(kind="readiness", payload=payload))
