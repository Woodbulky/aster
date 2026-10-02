import json
from functools import cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.agent.tools import Card, Ctx, ToolResult, register
from app.db import supabase as repo

KNOWLEDGE = Path(__file__).resolve().parents[4] / "knowledge"
SUPPORTED_PORTALS: dict[str, dict[str, str]] = {
    "mahadbt": {
        "name": "MahaDBT Scholarships (Maharashtra)",
        "url": "https://mahadbt.maharashtra.gov.in",
    },
}


@cache
def verified_packs(portal: str) -> dict[str, dict[str, Any]]:
    """scheme_key -> pack, verified packs only (knowledge/README.md). Missing folder = none."""
    out: dict[str, dict[str, Any]] = {}
    for f in sorted((KNOWLEDGE / portal).glob("[!_]*.json")):
        pack = json.loads(f.read_text(encoding="utf-8"))
        if pack.get("status") == "verified":
            out[pack["scheme_key"]] = pack
    return out


def _portal(raw: str) -> str | None:
    key = raw.strip().lower().replace(" ", "")
    return key if key in SUPPORTED_PORTALS else None


def _name(pack: dict[str, Any], lang: str) -> str:
    return pack["name"].get(lang) or pack["name"]["en"]


@register(
    "list_supported_forms",
    "List the portals/forms Aster can help with.",
    "Checking which forms I support",
)
def list_supported_forms(ctx: Ctx, _: Any) -> ToolResult:
    return ToolResult(
        ok=True,
        data=[
            {"portal": k, **v, "verified_schemes": len(verified_packs(k))}
            for k, v in SUPPORTED_PORTALS.items()
        ],
    )


class PortalArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    portal: str = Field(description="portal key from list_supported_forms, e.g. mahadbt")


@register(
    "suggest_schemes",
    "Show the user a card of schemes on a portal to choose from.",
    "Finding schemes for you",
    PortalArgs,
)
def suggest_schemes(ctx: Ctx, args: PortalArgs) -> ToolResult:
    # ponytail: stub until M5 — lists verified packs without eligibility ranking.
    portal = _portal(args.portal)
    if not portal:
        return ToolResult(
            ok=False, error=f"unsupported portal; supported: {list(SUPPORTED_PORTALS)}"
        )
    packs = verified_packs(portal)
    options = [
        {"portal": portal, "scheme_key": k, "name": _name(p, ctx.lang)} for k, p in packs.items()
    ] or [{"portal": portal, "scheme_key": None, "name": SUPPORTED_PORTALS[portal]["name"]}]
    note = "Eligibility ranking comes after research; the official authority decides."
    return ToolResult(
        ok=True,
        data={"options": options, "note": note},
        card=Card(kind="scheme_suggestions", payload={"options": options, "note": note}),
    )


class SetFormArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    portal: str = Field(description="portal key, e.g. mahadbt")
    scheme_key: str | None = Field(default=None, description="only a key from suggest_schemes")


@register(
    "set_form",
    "Record the form the user chose. Call it once the user clearly names a supported portal.",
    "Setting up your form",
    SetFormArgs,
)
def set_form(ctx: Ctx, args: SetFormArgs) -> ToolResult:
    portal = _portal(args.portal)
    if not portal:
        return ToolResult(
            ok=False, error=f"unsupported portal; supported: {list(SUPPORTED_PORTALS)}"
        )
    if args.scheme_key and args.scheme_key not in verified_packs(portal):
        return ToolResult(
            ok=False, error="unknown scheme_key; omit it or use one from suggest_schemes"
        )
    # The portal URL is always the official one, never an LLM-supplied link (guardrail 8).
    values = {
        "portal": portal,
        "scheme_key": args.scheme_key,
        "portal_url": SUPPORTED_PORTALS[portal]["url"],
    }
    row = repo.update_session(ctx.db, ctx.user_id, ctx.session["id"], values)
    if not row:
        return ToolResult(ok=False, error="session not updated")
    ctx.session.update(row)
    repo.write_audit(ctx.db, ctx.user_id, ctx.session["id"], "form.set", values, actor="agent")
    return ToolResult(ok=True, data=values)
