"""Documents phase tools (AGENT.md): the checklist card and the per-document field review."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.agent.phases import scheme_of
from app.agent.tools import Card, Ctx, ToolResult, register
from app.db import supabase as repo
from app.research.packs import usable_packs
from app.verify.pipeline import DOC_LABELS, review_payload

# Not in the packs' document lists, but most portals ask for them and Aster checks names and bank
# details against them.
RECOMMENDED = ("aadhaar", "ssc_marksheet", "bank_passbook")
RECOMMENDED_NOTE = "Recommended: Aster checks your details against it"
CHECKLIST_NOTE = (
    "Upload a clear photo or PDF of each one. Aster reads them, shows where every value came "
    "from, and checks them against each other."
)


def checklist(ctx: Ctx) -> dict[str, Any]:
    scheme = scheme_of(ctx.session) or ""
    pack = usable_packs().get(ctx.session.get("scheme_key") or "")
    items: list[dict[str, Any]] = []
    others: list[str] = []
    if pack:
        for d in pack.documents:
            if d.doc_type == "other":
                others.append(d.text.get(ctx.lang))
            elif all(i["doc_type"] != d.doc_type for i in items):
                items.append(
                    {
                        "doc_type": d.doc_type,
                        "label": d.text.get(ctx.lang),
                        # required_if is not evaluated yet: such documents show as optional
                        "required": d.required and not d.required_if,
                        "source": d.source.model_dump(),
                        "note": d.validity_note.get(ctx.lang) if d.validity_note else None,
                    }
                )
    else:
        row = repo.latest_research(ctx.db, ctx.user_id, ctx.session["id"], scheme, "documents")
        others = [it["text"] for it in (row or {}).get("items", [])]
    extra = RECOMMENDED if pack else (*RECOMMENDED, "income_certificate", "hsc_marksheet")
    for t in extra:
        if all(i["doc_type"] != t for i in items):
            item = {"doc_type": t, "label": DOC_LABELS[t], "required": False, "source": None}
            items.append(item | {"note": RECOMMENDED_NOTE})
    latest = {d["doc_type"]: d for d in repo.list_documents(ctx.db, ctx.user_id, ctx.session["id"])}
    for i in items:
        d = latest.get(i["doc_type"])
        i["status"] = d["status"] if d else "missing"
        i["document_id"] = d["id"] if d else None
    return {
        "session_id": ctx.session["id"],
        "scheme": ctx.session.get("scheme_name") or scheme,
        "items": items,
        "others": others,
        "note": CHECKLIST_NOTE,
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
    data = {
        "documents": [
            {k: i[k] for k in ("doc_type", "label", "required", "status")} for i in payload["items"]
        ],
        "also_bring": payload["others"],
    }
    return ToolResult(ok=True, data=data, card=Card(kind="document_checklist", payload=payload))


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
            data["why"] = FAILED_WHY.get(doc.get("error") or "", FAILED_WHY["internal"])
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
