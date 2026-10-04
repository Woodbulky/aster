"""Choosing a scholarship: any scheme. Schemes with a knowledge pack are ranked against the
profile; anything else is researched live (RESEARCH.md)."""

from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
from rapidfuzz import fuzz
from rapidfuzz.utils import default_process

from app.agent.tools import Card, Ctx, NoArgs, ToolResult, register
from app.agent.tools.eligibility import counts, evaluate_pack
from app.agent.tools.research import cached_research, reuse_research
from app.db import supabase as repo
from app.research.packs import portals, usable_packs

MAX_OPTIONS = 6
PACK_NAME_MATCH = 90
PACK_NAME_MARGIN = 10
SUGGEST_NOTE = (
    "Ranked by how many official criteria your profile meets. Not a decision: the scheme "
    "authority decides. Another scholarship? Just tell me its name."
)


@register(
    "list_supported_forms",
    "List the scholarship portals and the schemes Aster has verified rules for. Any other "
    "scholarship can still be researched live.",
    "Checking which scholarships I know",
)
def list_supported_forms(ctx: Ctx, _: Any) -> ToolResult:
    packs = usable_packs()
    return ToolResult(
        ok=True,
        data={
            "portals": [
                {
                    "portal": k,
                    "name": p.name,
                    "schemes": [
                        {"scheme_key": s.scheme_key, "name": s.name.get(ctx.lang)}
                        for s in packs.values()
                        if s.portal == k
                    ],
                }
                for k, p in portals().items()
            ],
            "other_schemes": "any other scholarship: set_form with scheme_name, then research",
        },
    )


class SuggestArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    portal: str | None = Field(
        default=None, description="only schemes of this portal (e.g. mahadbt); omit for all"
    )


@register(
    "suggest_schemes",
    "Show the user a card of scholarships with known official rules, ranked by how well their "
    "profile fits. Use it when the user is unsure which scholarship to apply for.",
    "Finding scholarships for you",
    SuggestArgs,
)
def suggest_schemes(ctx: Ctx, args: SuggestArgs) -> ToolResult:
    portal = (args.portal or "").strip().lower().replace(" ", "") or None
    packs = [p for p in usable_packs().values() if not portal or p.portal == portal]
    if not packs:
        return ToolResult(
            ok=False,
            error="no schemes with known rules for that portal; ask the user which scholarship "
            "they want and research it",
        )
    profile = repo.get_profile(ctx.db, ctx.user_id)
    options = []
    for p in packs:
        c = counts(evaluate_pack(p, profile, ctx.lang))
        options.append(
            {
                "portal": p.portal,
                "scheme_key": p.scheme_key,
                "name": p.name.get(ctx.lang),
                "draft": p.status != "verified",
                **c,
            }
        )
    options.sort(key=lambda o: (o["not_met"], -o["met"]))
    options = options[:MAX_OPTIONS]
    payload = {"options": options, "note": SUGGEST_NOTE}
    return ToolResult(
        ok=True,
        data={
            "options": [
                {k: o[k] for k in ("scheme_key", "name", "met", "not_met")} for o in options
            ]
        },
        card=Card(kind="scheme_suggestions", payload=payload),
    )


Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=200)]


class SetFormArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scheme_key: str | None = Field(
        default=None, description="a key from suggest_schemes / list_supported_forms"
    )
    scheme_name: Name | None = Field(
        default=None,
        description="the scholarship's name as the user said it, when it has no scheme_key",
    )

    @model_validator(mode="after")
    def _one(self) -> "SetFormArgs":
        if bool(self.scheme_key) == bool(self.scheme_name):
            raise ValueError("give exactly one of scheme_key or scheme_name")
        return self


def pack_for_name(name: str) -> str | None:
    """The pack a typed scheme name clearly means ("Shahu Maharaj EBC" -> the EBC pack), or None
    when no pack or more than one fits (e.g. "post matric scholarship": SC, ST and OBC packs).
    Seen live: the typed name went to web research and saved a rule from another scheme's page."""

    def fit(p: Any) -> float:
        names = [n for n in (p.name.en, p.name.mr, p.name.hi) if n]
        return max(fuzz.partial_token_set_ratio(name, n, processor=default_process) for n in names)

    scores = sorted(((fit(p), k) for k, p in usable_packs().items()), reverse=True)
    if not scores or scores[0][0] < PACK_NAME_MATCH:
        return None
    if len(scores) > 1 and scores[0][0] - scores[1][0] < PACK_NAME_MARGIN:
        return None
    return scores[0][1]


def scheme_values(args: SetFormArgs) -> dict[str, Any] | None:
    """The session columns for a chosen scheme, or None for an unknown scheme_key."""
    if args.scheme_name and (key := pack_for_name(args.scheme_name)):
        args = SetFormArgs(scheme_key=key)
    if not args.scheme_key:
        # No pack: no official URL is known yet, so none is stored.
        return {
            "portal": None,
            "scheme_key": None,
            "scheme_name": args.scheme_name,
            "portal_url": None,
        }
    pack = usable_packs().get(args.scheme_key)
    if not pack:
        return None
    # The portal URL comes from the reviewed knowledge files, never from the LLM (guardrail 8).
    return {
        "portal": pack.portal,
        "scheme_key": pack.scheme_key,
        "scheme_name": pack.name.en,
        "portal_url": portals()[pack.portal].url if pack.portal in portals() else None,
    }


UNKNOWN_KEY = "unknown scheme_key; use one from suggest_schemes or scheme_name"


@register(
    "set_form",
    "Record the scholarship the user chose. scheme_key for a known scheme; otherwise "
    "scheme_name (any scholarship), which you then research.",
    "Setting up your scholarship",
    SetFormArgs,
)
def set_form(ctx: Ctx, args: SetFormArgs) -> ToolResult:
    values = scheme_values(args)
    if values is None:
        return ToolResult(ok=False, error=UNKNOWN_KEY)
    args = SetFormArgs(scheme_key=values["scheme_key"]) if values["scheme_key"] else args
    row = repo.update_session(ctx.db, ctx.user_id, ctx.session["id"], values)
    if not row:
        return ToolResult(ok=False, error="session not updated")
    ctx.session.update(row)
    repo.write_audit(ctx.db, ctx.user_id, ctx.session["id"], "form.set", values, actor="agent")
    data = {**values, "known_rules": bool(args.scheme_key)}
    # Another student already researched this scheme: reuse it (no LLM rounds) unless this
    # session already has research for it.
    if (
        args.scheme_name
        and (row := cached_research(ctx, args.scheme_name))
        and not repo.latest_research(ctx.db, ctx.user_id, ctx.session["id"], args.scheme_name)
        and (card := reuse_research(ctx, args.scheme_name, row))
    ):
        data["research"] = (
            f"already found earlier (read on {str(row['saved_at'])[:10]}), unverified: the card "
            "shows it; do not research again unless the user asks"
        )
        return ToolResult(ok=True, data=data, card=card)
    return ToolResult(ok=True, data=data)


@register(
    "mark_submitted",
    "Record that the user says they submitted this scholarship's form on the official portal "
    "themselves. Call it only when they say so.",
    "Marking this application as submitted",
)
def mark_submitted(ctx: Ctx, _: NoArgs) -> ToolResult:
    # The user's word, not a check: Aster never sees or confirms the submission (guardrail 5).
    row = repo.update_session(
        ctx.db, ctx.user_id, ctx.session["id"], {"phase": "done", "status": "done"}
    )
    if not row:
        return ToolResult(ok=False, error="session not updated")
    ctx.session.update(row)
    repo.write_audit(
        ctx.db, ctx.user_id, ctx.session["id"], "form.submitted_by_user", {}, actor="user"
    )
    return ToolResult(
        ok=True,
        data={"rule": "the user said they submitted; Aster did not see or confirm it"},
    )


@register(
    "new_application",
    "Start a separate application for another scholarship, keeping this one as it is. The "
    "profile is reused; the new scholarship gets its own research and documents. scheme_key for "
    "a known scheme; otherwise scheme_name.",
    "Starting a new application",
    SetFormArgs,
)
def new_application(ctx: Ctx, args: SetFormArgs) -> ToolResult:
    values = scheme_values(args)
    if values is None:
        return ToolResult(ok=False, error=UNKNOWN_KEY)
    if values["scheme_name"] == ctx.session.get("scheme_name"):
        return ToolResult(ok=False, error="that is this application's scholarship already")
    row = repo.create_session(ctx.db, ctx.user_id, values)
    if not row:
        return ToolResult(ok=False, error="application not created")
    repo.write_audit(
        ctx.db, ctx.user_id, row["id"], "form.set", {**values, "from": ctx.session["id"]}, "agent"
    )
    payload = {"session_id": row["id"], "scheme": values["scheme_name"]}
    return ToolResult(
        ok=True,
        data={**payload, "rule": "the card opens it; Aster researches it there"},
        card=Card(kind="new_application", payload=payload),
    )
