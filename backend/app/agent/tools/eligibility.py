"""check_eligibility: pack criteria evaluated in code against the confirmed profile (RESEARCH.md
"Eligibility evaluation"). The LLM only phrases the result. Guardrail 1: every result reads
"meets / does not meet / unknown — per <source>", never a final verdict."""

from datetime import date
from typing import Any
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict
from supabase import Client

from app.agent.phases import not_applicable_fields, scheme_of
from app.agent.prompts import t
from app.agent.tools import Card, Ctx, ToolResult, register
from app.db import supabase as repo
from app.research.packs import Pack, current_cycle, freshness, usable_packs
from app.verify import requirements
from app.verify.contradictions import effective
from app.verify.requirements import year_note
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


def _reason(status: str, needs: list[dict[str, Any]], src: str, note: str | None) -> str:
    """One line per criterion. Never a verdict (guardrail 1): an unknown one names the exact
    condition still unanswered, "Needs confirmation — ..."."""
    if status == "met":
        return f"Meets this — per {src}"
    if status == "not_met":
        return f"Does not meet this — per {src}"
    if status == "not_applicable":
        return f"Not applicable — {note}"
    asks = [n["text"] for n in needs if n["kind"] == "question"]
    fields = [n["field"].replace("_", " ") for n in needs if n["kind"] == "profile"]
    if asks:
        return "Needs confirmation — " + " ".join(asks)
    if fields:
        return f"Needs confirmation — your profile has no {', '.join(fields)} yet"
    return f"Needs confirmation — Aster can't check this from your answers; read the rule at {src}"


NO_HSC = (
    "Needs confirmation — this rule asks for 12th results, which don't apply on your path (you "
    "joined after 10th or a diploma). Check the official rule for your route at {src}"
)


def _needs(missing: list[str], pack: Pack, lang: str) -> list[dict[str, Any]]:
    """What is still unanswered, as the question to ask: a pack question (tap an option) or a
    profile field (the user tells Aster, a card confirms it)."""
    qs = {q.id: q for q in pack.questions}
    out: list[dict[str, Any]] = []
    for m in missing:
        kind, _, key = m.partition(".")
        if kind == "answers" and key in qs:
            q = qs[key]
            out.append(
                {"kind": "question", "id": key, "text": q.text.get(lang), "options": q.options}
            )
        elif kind == "profile":
            out.append({"kind": "profile", "field": key, "text": t(lang, f"ask.{key}") or key})
    return out


def facts_for(
    profile: dict[str, Any] | None, answers: dict[str, Any] | None, cycle: str | None
) -> dict[str, Any]:
    """What a pack's logic can read: profile.*, answers.<question id> (this application's) and
    computed.cycle_start (the application cycle's first year, e.g. 2026 for "2026-27")."""
    return {
        "profile": profile or {},
        "answers": answers or {},
        "computed": {"cycle_start": int((cycle or current_cycle())[:4])},
    }


def checked_line(pack: Pack) -> str | None:
    """ "Rules for 2026-27, checked on 2026-10-03." (+ "check them again at the official site" when
    that is too long ago). None for a draft: its DRAFT badge says it."""
    if pack.status != "verified":
        return None
    f = freshness(pack)
    line = f"Rules for {f['cycle']}, checked by the team on {f['rules_checked_on']}."
    return line + (
        " That was a while ago: confirm them at the official site." if f["rules_stale"] else ""
    )


def evaluate_pack(
    pack: Pack,
    profile: dict[str, Any] | None,
    lang: str,
    answers: dict[str, Any] | None = None,
    cycle: str | None = None,
) -> list[dict[str, Any]]:
    # A rule is for its own cycle ("admitted in 2026-27"), whichever cycle the session is in.
    facts = facts_for(profile, answers, pack.academic_year or cycle)
    no_hsc = {f"profile.{k}" for k in not_applicable_fields(profile)}
    out = []
    for c in pack.criteria:
        src, note = site(c.source.url), c.applies_note.get(lang) if c.applies_note else None
        status: str = "unknown"
        missing: list[str] = []
        if c.applies_if is not None:
            guard, missing = evaluate(c.applies_if, facts)
            if guard == "not_met":
                status = "not_applicable"
        if status == "unknown" and not missing:  # the rule applies: check it
            status, missing = evaluate(c.logic, facts)
        # 12th results on a path with no 12th: not asked, not a verdict either.
        no_path = status == "unknown" and bool(missing) and set(missing) <= no_hsc
        needs = [] if no_path else _needs(missing, pack, lang)
        if status == "unknown" and not needs:
            needs = [{"kind": "read", "text": c.text.get(lang)}]
        fields = [n["field"] for n in needs if n["kind"] == "profile"]
        ask = c.ask_if_unknown.field_key if c.ask_if_unknown else None
        reason = NO_HSC.format(src=src) if no_path else _reason(status, needs, src, note)
        out.append(
            {
                "id": c.id,
                "text": c.text.get(lang),
                "status": status,
                "reason": reason,
                "source": c.source.model_dump(),
                "ask_field": (ask if ask in fields else fields[0] if fields else None),
                "needs": needs if status == "unknown" else [],
            }
        )
    return out


def counts(results: list[dict[str, Any]]) -> dict[str, int]:
    keys = ("met", "not_met", "unknown", "not_applicable")
    return {k: sum(r["status"] == k for r in results) for k in keys}


def _pack_card(
    db: Client, user_id: str, session: dict[str, Any], lang: str, pack: Pack
) -> dict[str, Any]:
    profile = repo.get_profile(db, user_id)
    # This application's answers to the scheme's questions (checks.record_answer stores them).
    rows = repo.list_field_values(db, user_id, session["id"])
    answers = requirements.answers(effective(rows, set()))
    results = evaluate_pack(pack, profile, lang, answers, session.get("academic_year"))
    today = date.today()
    fresh = freshness(pack)
    return {
        "scheme_key": pack.scheme_key,
        "name": pack.name.get(lang),
        "origin": "pack",
        "draft": pack.status != "verified",
        "results": results,
        "counts": counts(results),
        "deadlines": [
            {
                "label": d.label.get(lang),
                "date": d.date.isoformat() if d.date else None,
                "passed": bool(d.date and d.date < today),
                # Deadlines move (extensions, a new portal): say when this one was last checked.
                "unconfirmed_since": fresh["deadlines_checked_on"] or "never"
                if fresh["deadlines_stale"]
                else None,
                "source": d.source.model_dump(),
            }
            for d in pack.deadlines
        ],
        "checked": checked_line(pack),
        "note": NOTE,
    }


def _live_card(session: dict[str, Any], scheme: str, row: dict[str, Any]) -> dict[str, Any]:
    results = [
        {
            "id": f"live_{i}",
            "text": it["text"],
            "status": "unknown",
            "reason": f"Unverified — from {it['site']} on {it['fetched_on']}; check this rule "
            "yourself" + year_note(it, session.get("academic_year")),
            "source": {"url": it["source_url"], "quote": it["quote"]},
            "ask_field": None,
            "needs": [{"kind": "read", "text": it["text"]}],
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
        "checked": None,
        "note": LIVE_NOTE,
    }


def eligibility_payload(
    db: Client, user_id: str, session: dict[str, Any], lang: str
) -> dict[str, Any] | None:
    """The eligibility card for the session's scheme (a pack, else saved live research), from the
    profile and this application's answers. None: no scheme, or nothing researched yet. Shared by
    the tool and the card's answer endpoint, so a tap and a spoken answer give the same card."""
    scheme = scheme_of(session)
    if not scheme:
        return None
    pack = usable_packs().get(session.get("scheme_key") or "")
    if pack:
        return _pack_card(db, user_id, session, lang, pack)
    row = repo.latest_research(db, user_id, session["id"], scheme, kind="eligibility")
    return _live_card(session, scheme, row) if row else None


def card_result(payload: dict[str, Any]) -> ToolResult:
    """The tool result for an eligibility payload: what the model may say, plus the card."""
    data = {
        "scheme": payload["name"],
        "origin": payload["origin"],
        "draft": payload["draft"],
        "counts": payload["counts"],
        "criteria": [
            {
                "text": r["text"],
                "status": r["status"],
                "ask_field": r["ask_field"],
                "needs": r["needs"],
                "source": site(r["source"]["url"]),
            }
            for r in payload["results"]
        ],
        "deadlines": payload["deadlines"],
        "rule": "Say which criteria look met / not met / need confirmation per the source. Never "
        "say the user is or is not eligible. A status unknown criterion lists its exact "
        "unanswered condition(s) in needs: kind profile -> ask that value, then "
        "propose_profile_update; kind question -> ask it, then answer_requirement with the "
        "question id and one of its options; kind read -> the user reads it at the source, "
        "mention it briefly and don't quiz them. not_applicable criteria need nothing.",
    }
    return ToolResult(ok=True, data=data, card=Card(kind="eligibility", payload=payload))


class CheckArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


@register(
    "check_eligibility",
    "Check the chosen scheme's official criteria against the user's confirmed profile and this "
    "application's answers, and show the eligibility card. Call it again after the user "
    "confirms a missing profile value.",
    "Checking the official rules against your profile",
    CheckArgs,
)
def check_eligibility(ctx: Ctx, _: CheckArgs) -> ToolResult:
    if not scheme_of(ctx.session):
        return ToolResult(ok=False, error="no scheme chosen yet")
    payload = eligibility_payload(ctx.db, ctx.user_id, ctx.session, ctx.lang)
    if payload is None:
        return ToolResult(ok=False, error="no eligibility research saved for this scheme")
    return card_result(payload)
