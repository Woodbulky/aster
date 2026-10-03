"""check_eligibility: pack criteria evaluated in code against the confirmed profile (RESEARCH.md
"Eligibility evaluation"). The LLM only phrases the result. Guardrail 1: every result reads
"meets / does not meet / unknown — per <source>", never a final verdict."""

from datetime import date
from typing import Any
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict

from app.agent.phases import scheme_of
from app.agent.tools import Card, Ctx, ToolResult, register
from app.db import supabase as repo
from app.research.packs import Pack, usable_packs
from app.verify.rules_engine import evaluate

NOTE = (
    "Aster does not decide eligibility. These checks follow the official rules quoted below; "
    "the scheme authority makes the final decision."
)
LIVE_NOTE = (
    "Unverified: found on the web by Aster and not checked by the team. Read each rule at its "
    "source; the scheme authority makes the final decision."
)


def site(url: str) -> str:
    host = urlsplit(url).hostname or url
    return host.removeprefix("www.")


def _reason(status: str, missing: list[str], has_logic: bool, src: str) -> str:
    if status == "met":
        return f"Meets this — per {src}"
    if status == "not_met":
        return f"Does not meet this — per {src}"
    if missing:
        fields = ", ".join(m.removeprefix("profile.").replace("_", " ") for m in missing)
        return f"Unknown — your profile has no {fields} yet"
    if has_logic:
        return "Unknown — Aster could not compare this with your profile"
    return f"Unknown — Aster can't check this from your profile; read the rule at {src}"


def evaluate_pack(pack: Pack, profile: dict[str, Any] | None, lang: str) -> list[dict[str, Any]]:
    facts = {"profile": profile or {}}
    out = []
    for c in pack.criteria:
        status, missing = evaluate(c.logic, facts)
        out.append(
            {
                "id": c.id,
                "text": c.text.get(lang),
                "status": status,
                "reason": _reason(status, missing, c.logic is not None, site(c.source.url)),
                "source": c.source.model_dump(),
                "ask_field": c.ask_if_unknown.field_key
                if status == "unknown" and c.ask_if_unknown
                else None,
            }
        )
    return out


def counts(results: list[dict[str, Any]]) -> dict[str, int]:
    return {k: sum(r["status"] == k for r in results) for k in ("met", "not_met", "unknown")}


def _pack_card(ctx: Ctx, pack: Pack) -> dict[str, Any]:
    profile = repo.get_profile(ctx.db, ctx.user_id)
    results = evaluate_pack(pack, profile, ctx.lang)
    today = date.today()
    return {
        "scheme_key": pack.scheme_key,
        "name": pack.name.get(ctx.lang),
        "origin": "pack",
        "draft": pack.status != "verified",
        "results": results,
        "counts": counts(results),
        "deadlines": [
            {
                "label": d.label.get(ctx.lang),
                "date": d.date.isoformat() if d.date else None,
                "passed": bool(d.date and d.date < today),
                "source": d.source.model_dump(),
            }
            for d in pack.deadlines
        ],
        "note": NOTE,
    }


def _live_card(ctx: Ctx, scheme: str, row: dict[str, Any]) -> dict[str, Any]:
    results = [
        {
            "id": f"live_{i}",
            "text": it["text"],
            "status": "unknown",
            "reason": f"Unverified — from {it['site']} on {it['fetched_on']}; check this rule "
            "yourself",
            "source": {"url": it["source_url"], "quote": it["quote"]},
            "ask_field": None,
        }
        for i, it in enumerate(row["items"])
    ]
    return {
        "scheme_key": None,
        "name": scheme,
        "origin": "live",
        "draft": False,
        "results": results,
        "counts": counts(results),
        "deadlines": [],
        "note": LIVE_NOTE,
    }


class CheckArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


@register(
    "check_eligibility",
    "Check the chosen scheme's official criteria against the user's confirmed profile and show "
    "the eligibility card. Call it again after the user confirms a missing profile value.",
    "Checking the official rules against your profile",
    CheckArgs,
)
def check_eligibility(ctx: Ctx, _: CheckArgs) -> ToolResult:
    scheme = scheme_of(ctx.session)
    if not scheme:
        return ToolResult(ok=False, error="no scheme chosen yet")
    pack = usable_packs().get(ctx.session.get("scheme_key") or "")
    if pack:
        payload = _pack_card(ctx, pack)
    else:
        row = repo.latest_research(
            ctx.db, ctx.user_id, ctx.session["id"], scheme, kind="eligibility"
        )
        if not row:
            return ToolResult(ok=False, error="no eligibility research saved for this scheme")
        payload = _live_card(ctx, scheme, row)
    data = {
        "scheme": payload["name"],
        "origin": payload["origin"],
        "draft": payload["draft"],
        "counts": payload["counts"],
        "criteria": [
            {"text": r["text"], "status": r["status"], "ask_field": r["ask_field"]}
            | {"source": site(r["source"]["url"])}
            for r in payload["results"]
        ],
        "deadlines": payload["deadlines"],
        "rule": "Say which criteria look met / not met / unknown per the source. Never say the "
        "user is or is not eligible. For unknowns with ask_field, ask for that value.",
    }
    return ToolResult(ok=True, data=data, card=Card(kind="eligibility", payload=payload))
