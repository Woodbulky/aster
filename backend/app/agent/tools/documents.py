"""Documents phase tools (AGENT.md): the checklist card, document questions and the
per-document field review."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from rapidfuzz import fuzz

from app.agent.phases import scheme_of
from app.agent.tools import Card, Ctx, ToolResult, register
from app.agent.tools.eligibility import card_result, eligibility_payload
from app.agent.tools.flags import REASON_FROM_USER
from app.db import supabase as repo
from app.verify.checks import AnswerError, record_answer, requirement_rows, store_answer
from app.verify.extraction import DOC_LABELS
from app.verify.pipeline import review_payload
from app.verify.validator import norm

CHECKLIST_NOTE = (
    "Upload a clear photo or PDF of each one. Aster reads them, shows where every value came "
    "from, and checks them against each other."
)


def checklist(ctx: Ctx, rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """The checklist card: one item per scheme requirement (requirements.status rows)."""
    if rows is None:
        rows = requirement_rows(ctx.db, ctx.user_id, ctx.session, ctx.lang)
    return {
        "session_id": ctx.session["id"],
        "scheme": ctx.session.get("scheme_name") or scheme_of(ctx.session) or "",
        "items": [r | {"required": r["need"] == "required"} for r in rows],
        "note": CHECKLIST_NOTE,
    }


def _brief(payload: dict[str, Any]) -> dict[str, Any]:
    """What the model sees of the checklist: no sources, the open questions spelled out."""
    out = []
    for i in payload["items"]:
        item = {"document": i["label"], "need": i["need"], "status": i["status"]}
        if (ask := i.get("ask")) and ask.get("id"):
            item |= {"question_id": ask["id"], "question": ask["text"], "options": ask["options"]}
        elif ask:
            item["needs_profile_field"] = ask.get("profile_field")
        out.append(item)
    return {
        "documents": out,
        "rule": "need=ask: ask the user the question (in their language), then record the "
        "answer with answer_requirement. need=later: not uploaded now.",
    }


class NoArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


@register(
    "request_documents",
    "Show the document checklist card (upload buttons) for the chosen scholarship and move on to "
    "the documents step. Call it when the user wants to continue to documents.",
    "Preparing your document checklist",
    NoArgs,
)
def request_documents(ctx: Ctx, _: NoArgs) -> ToolResult:
    if not scheme_of(ctx.session):
        return ToolResult(ok=False, error="no scheme chosen yet")
    if ctx.session["phase"] == "eligibility":
        old = ctx.session["phase"]
        row = repo.update_session(ctx.db, ctx.user_id, ctx.session["id"], {"phase": "documents"})
        ctx.session.update(row or {"phase": "documents"})
        payload = {"from": old, "to": "documents"}
        repo.write_audit(ctx.db, ctx.user_id, ctx.session["id"], "phase.changed", payload)
    payload = checklist(ctx)
    return ToolResult(
        ok=True, data=_brief(payload), card=Card(kind="document_checklist", payload=payload)
    )


class AnswerArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question_id: str = Field(description="question id (a checklist or eligibility question)")
    answer: str = Field(description="one of that question's options, e.g. yes, no, fresh")
    user_words: str = Field(
        min_length=1, max_length=200, description="the user's words that answer it, copied"
    )


@register(
    "answer_requirement",
    "Record the user's answer to a scheme question (e.g. whether they live in a hostel): it "
    "settles an eligibility condition or decides whether a document is needed. Only when they "
    "clearly answered it just now.",
    "Noting your answer",
    AnswerArgs,
)
def answer_requirement(ctx: Ctx, args: AnswerArgs) -> ToolResult:
    # Guardrail 2: the answer's source is the user's own message (set by the orchestrator).
    if not ctx.message_id or ctx.input_mode not in ("voice", "text"):
        return ToolResult(ok=False, error="only the user's own words can answer this; ask them")
    # A guessed "no" would make a required document "not needed": the user must have said it.
    if fuzz.partial_ratio(norm(args.user_words), norm(ctx.user_text)) < REASON_FROM_USER:
        return ToolResult(ok=False, error="user_words must be what the user just said; ask them")
    via = "voice" if ctx.input_mode == "voice" else "text"
    # In the eligibility phase the answer settles a criterion: store it and show that card (no
    # documents to re-check yet). Later it decides a document: re-check, show the checklist.
    on_eligibility = ctx.session["phase"] == "eligibility"
    try:
        rows = (store_answer if on_eligibility else record_answer)(
            ctx.db,
            ctx.user_id,
            ctx.session,
            args.question_id,
            args.answer,
            source_type=via,
            message_id=ctx.message_id,
            via=via,
            lang=ctx.lang,
        )
    except AnswerError as e:
        return ToolResult(ok=False, error=str(e))
    if on_eligibility:
        elig = eligibility_payload(ctx.db, ctx.user_id, ctx.session, ctx.lang)
        if elig:
            return card_result(elig)
    payload = checklist(ctx, rows)
    return ToolResult(
        ok=True, data=_brief(payload), card=Card(kind="document_checklist", payload=payload)
    )


class StatusArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_id: str | None = Field(
        default=None, description="show the field review card for this document"
    )


@register(
    "get_document_status",
    "List the uploaded documents and their reading status. With document_id, show the values "
    "read from that document, each with its source.",
    "Checking your documents",
    StatusArgs,
)
def get_document_status(ctx: Ctx, args: StatusArgs) -> ToolResult:
    if args.document_id:
        doc = repo.get_document(ctx.db, ctx.user_id, args.document_id)
        if not doc or doc["session_id"] != ctx.session["id"]:
            return ToolResult(ok=False, error="no such document in this session")
        fields = repo.list_field_values(ctx.db, ctx.user_id, ctx.session["id"])
        payload = review_payload(doc, fields)
        # Seen live: "could_not_read: [10th percentage]" was spoken as "I could not read your
        # marksheet". The status words say plainly whether the document itself was read.
        data = {
            "document": payload["label"],
            "status": STATUS_WORDS[doc["status"]],
            "values_found": {f["label"]: f["value"] for f in payload["fields"]},
            "not_found_on_document": payload["unreadable"],
        }
        if doc["status"] == "failed":
            code = (doc.get("error") or "internal").split(":")[0]
            data["why"] = FAILED_WHY.get(code, FAILED_WHY["internal"])
        card = Card(kind="field_review", payload=payload) if doc["status"] == "extracted" else None
        return ToolResult(ok=True, data=data, card=card)
    docs = repo.list_documents(ctx.db, ctx.user_id, ctx.session["id"])
    return ToolResult(
        ok=True,
        data=[
            {"document": DOC_LABELS.get(d["doc_type"], d["doc_type"]), "document_id": d["id"]}
            | {"status": STATUS_WORDS[d["status"]]}
            for d in docs
        ],
    )


STATUS_WORDS = {
    "uploaded": "still reading",
    "processing": "still reading",
    "extracted": "read",
    "failed": "could not be read",
}
FAILED_WHY = {
    "ocr_unavailable": "the text reader is offline right now; try again in a few minutes",
    "llm_unavailable": "Aster's reader is busy right now; try again in a minute",
    "internal": "something went wrong reading it; upload it again or try a clearer photo",
}
