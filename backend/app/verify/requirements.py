"""Scheme document requirements: one identity and one status per requirement, from a knowledge
pack or from live research. The checklist card, the missing-document check and the readiness card
all read `status()`, so they can't disagree.

need:   required | optional | ask (a condition is unknown: a question, never silently optional)
        | not_needed (its condition is false) | later (asked after applying, e.g. by the college)
status: the latest matching document's status, or "missing"."""

import re
from typing import Any, Literal

from pydantic import BaseModel

from app.verify.contradictions import best
from app.verify.rules_engine import evaluate, variables

Row = dict[str, Any]
Need = Literal["required", "optional", "ask", "not_needed", "later"]
ANSWER = "answers."  # field_values.field_key prefix of an answer to a requirement question
YES_NO = ["yes", "no"]

# The first match wins; anything else is "other" (also used by scripts/promote_research.py).
DOC_GUESS = (
    (r"income", "income_certificate"),
    (r"validity", "caste_validity"),
    (r"caste", "caste_certificate"),
    (r"domicile|residence", "domicile_certificate"),
    (r"aadha?a?r", "aadhaar"),
    (r"\b(10th|ssc|class 10|matric)", "ssc_marksheet"),
    (r"\b(12th|hsc|class 12)", "hsc_marksheet"),
    (r"bank|passbook", "bank_passbook"),
    (r"fee", "fee_receipt"),
    (r"admission|bonafide", "admission_letter"),
    (r"gap", "gap_certificate"),
)


def doc_type(text: str) -> str:
    return next((t for rx, t in DOC_GUESS if re.search(rx, text, re.I)), "other")


class Req(BaseModel):
    id: str
    label: str
    doc_types: list[str]  # the first is the upload slot; any of them satisfies it
    required: bool
    condition: dict[str, Any] | None = None  # over profile.* and answers.*
    questions: list[Row] = []  # the questions `condition` reads: {id, text, options, source}
    stage: str = "apply"
    period: str | None = None
    holder: str = "student"
    source: Row | None = None
    note: str | None = None
    origin: Literal["pack", "live", "recommended"] = "pack"


def from_pack(pack: Any, lang: str) -> list[Req]:
    qs = {
        f"{ANSWER}{q.id}": {
            "id": q.id,
            "text": q.text.get(lang),
            "options": q.options,
            "source": q.source.model_dump() if q.source else None,
        }
        for q in pack.questions
    }
    return [
        Req(
            id=d.id,
            label=d.text.get(lang),
            doc_types=[d.doc_type, *d.also_accepts],
            required=d.required,
            condition=d.required_if,
            questions=[qs[v] for v in sorted(variables(d.required_if)) if v in qs],
            stage=d.stage,
            period=d.period.get(lang) if d.period else None,
            holder=d.holder,
            source=d.source.model_dump(),
            note=d.validity_note.get(lang) if d.validity_note else None,
        )
        for d in pack.documents
    ]


def year_note(it: Row, cycle: str | None) -> str:
    """ " (the page is about 2025-26)" when the page states another year than this application's."""
    y = it.get("year_on_page")
    return (
        f" (the page is about {y}, not {cycle}: check the current rules)"
        if y and cycle and y != cycle
        else ""
    )


def from_live(items: list[Row], cycle: str | None = None) -> list[Req]:
    """Quote-checked research items (tools/research.save_research). required: "yes" (default for
    items saved before it existed), "if" (a condition the page states: asked as a question) or
    "optional"."""
    out = []
    for i, it in enumerate(items):
        rid = f"live_{i}"
        types = it.get("doc_types") or [doc_type(it["text"])]
        req, cond, qs = it.get("required", "yes"), None, []
        if req == "if":
            src = {"url": it["source_url"], "quote": it["quote"]}
            when = it.get("condition") or it["text"]
            qs = [
                {
                    "id": rid,
                    "text": f"Does this apply to you? Only if: {when} (per {it.get('site', '')})",
                    "options": YES_NO,
                    "source": src,
                }
            ]
            cond = {"==": [{"var": f"{ANSWER}{rid}"}, "yes"]}
        out.append(
            Req(
                id=rid,
                label=it["text"],
                doc_types=types,
                required=req != "optional",
                condition=cond,
                questions=qs,
                source={"url": it["source_url"], "quote": it["quote"]},
                note=f"Unverified — from {it.get('site', '')} on {it.get('fetched_on', '')}"
                + year_note(it, cycle),
                origin="live",
            )
        )
    return out


def answers(eff: dict[str, list[Row]]) -> dict[str, Any]:
    """The user's answers to requirement questions (effective field values answers.<id>)."""
    return {
        k.removeprefix(ANSWER): b["value"]
        for k, rows in eff.items()
        if k.startswith(ANSWER) and (b := best(rows))
    }


def _matches(r: Req, d: Row) -> bool:
    # A document uploaded for this requirement, or any read type it accepts ("other" only counts
    # for the requirement it was uploaded for: two "other" requirements are two documents).
    if d.get("requirement_id"):
        return d["requirement_id"] == r.id or (
            d["doc_type"] != "other" and d["doc_type"] in r.doc_types
        )
    return d["doc_type"] != "other" and d["doc_type"] in r.doc_types


def need(r: Req, facts: Row) -> tuple[Need, list[str]]:
    """-> (need, the variables still unknown)."""
    if r.stage != "apply":
        return "later", []
    if r.condition is None:
        return ("required" if r.required else "optional"), []
    st, missing = evaluate(r.condition, facts)
    if st == "met":
        return "required", []
    return ("not_needed", []) if st == "not_met" else ("ask", missing)


def status(reqs: list[Req], profile: Row | None, ans: Row, docs: list[Row]) -> list[Row]:
    """docs: the session's documents, oldest first. -> each requirement + need, status,
    document_id and (need == "ask") the question to ask or the profile field missing."""
    facts = {"profile": profile or {}, "answers": ans}
    out = []
    for r in reqs:
        n, missing = need(r, facts)
        doc = next((d for d in reversed(docs) if _matches(r, d)), None)
        ask = None
        if n == "ask":
            want = {f"{ANSWER}{q['id']}": q for q in r.questions}
            ask = next((want[m] for m in missing if m in want), None) or {
                "profile_field": missing[0].removeprefix("profile.") if missing else None
            }
        out.append(
            r.model_dump(exclude={"condition"})
            | {
                "need": n,
                "status": doc["status"] if doc else "missing",
                "document_id": doc["id"] if doc else None,
                "ask": ask,
            }
        )
    return out


def blocking(rows: list[Row]) -> list[Row]:
    """status() rows that stop the form being ready: required and not read yet, or a question
    whose answer decides it (unless a matching document is already read)."""
    return [r for r in rows if r["need"] in ("required", "ask") and r["status"] != "extracted"]
