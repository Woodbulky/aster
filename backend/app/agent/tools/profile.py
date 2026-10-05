from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.agent.phases import missing_core
from app.agent.prompts import t
from app.agent.tools import Card, Ctx, ToolResult, register
from app.api.me import ProfileIn
from app.db import supabase as repo

HIDDEN = ("id", "email", "preferred_language", "created_at", "updated_at")
MASKED = ("caste", "religion", "mobile", "aadhaar_last4")
# Same options as the web profile form, so a confirmed value shows up in its selects.
CHOICES: dict[str, tuple[str, ...]] = {
    "gender": ("Female", "Male", "Transgender"),
    "category": ("Open", "OBC", "SC", "ST", "VJ/NT", "SBC", "SEBC", "EWS"),
    "entry_qualification": ("ssc", "hsc", "diploma", "graduation"),
    "course_mode": ("regular", "part_time", "distance", "online"),
}


def masked(profile: dict[str, Any] | None) -> dict[str, Any]:
    """Filled fields only; sensitive ones read "provided" (AGENT.md get_profile)."""
    return {
        k: "provided" if k in MASKED else v
        for k, v in (profile or {}).items()
        if k not in HIDDEN and v not in (None, "")
    }


@register(
    "get_profile",
    "Read the user's saved profile (sensitive fields masked).",
    "Checking your profile",
)
def get_profile(ctx: Ctx, _: Any) -> ToolResult:
    p = repo.get_profile(ctx.db, ctx.user_id)
    return ToolResult(ok=True, data={"profile": masked(p), "missing_core": missing_core(p)})


class ProposeArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    updates: dict[str, str | int | float] = Field(
        description=f"field_key -> value the user said. Keys: {', '.join(ProfileIn.model_fields)}. "
        "Dates YYYY-MM-DD, numbers as plain digits, text in English letters as on documents "
        "(पुणे -> Pune). gender: Female|Male|Transgender. "
        "category: Open|OBC|SC|ST|VJ/NT|SBC|SEBC|EWS. "
        "entry_qualification (what the current course was joined after): ssc = after 10th "
        "(diploma, ITI, 11th-12th) | hsc = after 12th | diploma = after a diploma (lateral entry) "
        "| graduation = after a degree. "
        "course_mode: regular|part_time|distance|online. "
        "admission_year: the year the current course was joined."
    )
    evidence: Literal["voice", "text"] = "text"


@register(
    "propose_profile_update",
    "Show the user a card to confirm profile values they told you. Nothing is saved until they "
    "confirm. Never say a value is saved before that.",
    "Preparing a card for you to check",
    ProposeArgs,
)
def propose_profile_update(ctx: Ctx, args: ProposeArgs) -> ToolResult:
    # ProfileIn rejects unknown keys and anything but Aadhaar last-4 (guardrail 6).
    values = ProfileIn.model_validate(args.updates).model_dump(mode="json", exclude_none=True)
    bad = [
        f"{k} must be one of {opts}"
        for k, opts in CHOICES.items()
        if values.get(k, opts[0]) not in opts
    ]
    if bad:
        return ToolResult(ok=False, error="; ".join(bad))
    if not values:
        return ToolResult(ok=False, error="no values to propose")
    row = repo.create_proposal(
        ctx.db,
        ctx.user_id,
        {
            "session_id": ctx.session["id"],
            "updates": values,
            "evidence": args.evidence,
            "message_id": ctx.message_id,  # set by the orchestrator, never by the LLM
        },
    )
    if not row:
        return ToolResult(ok=False, error="proposal not stored")
    return ToolResult(
        ok=True,
        data={"proposal_id": row["id"], "status": "waiting for the user to confirm the card"},
        card=Card(kind="confirm_profile", payload={"proposal_id": row["id"], "updates": values}),
    )


class WhyArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field_key: str


@register(
    "explain_why_asked",
    "Get the approved explanation of why a profile field is needed, in the user's language.",
    "Looking up why this is asked",
    WhyArgs,
)
def explain_why_asked(ctx: Ctx, args: WhyArgs) -> ToolResult:
    text = t(ctx.lang, f"why.{args.field_key}") or t(ctx.lang, "why._generic")
    return ToolResult(ok=True, data={"text": text, "source": t(ctx.lang, "why._source")})
