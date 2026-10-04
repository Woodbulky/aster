"""Documents (VERIFICATION.md). The client uploads to Storage <uid>/<sid>/<document_id>.<ext>
(storage RLS: own folder only), then calls this; all table writes stay on the backend."""

import json
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.api.me import require_consent
from app.audit import fetch as fetch_audit
from app.audit import verify_chain
from app.config import Settings, get_settings
from app.db import supabase as repo
from app.deps import Db, UserId
from app.research.packs import DOC_TYPES
from app.verify.checks import ResolveError, readiness, resolve
from app.verify.pipeline import process_document

router = APIRouter(prefix="/api/sessions/{session_id}")

EXT = {"application/pdf": "pdf", "image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}


class DocumentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_id: UUID
    doc_type: Literal[DOC_TYPES]  # type: ignore[valid-type]
    mime: Literal["application/pdf", "image/jpeg", "image/png", "image/webp"]
    quality: dict[str, float] | None = Field(default=None, max_length=5)  # client blur check


def _session(db: Any, user_id: str, session_id: UUID) -> dict[str, Any]:
    row = repo.get_session(db, user_id, str(session_id))
    if not row:
        raise HTTPException(404, "session not found")
    return row


@router.post("/documents", status_code=202)
def add_document(
    session_id: UUID,
    body: DocumentIn,
    tasks: BackgroundTasks,
    db: Db,
    user_id: UserId,
    s: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    """Registers an uploaded file and starts the pipeline. Posting a failed document again
    retries it."""
    _session(db, user_id, session_id)
    require_consent(db, user_id, "documents")  # before anything reads the file
    doc_id, sid = str(body.document_id), str(session_id)
    doc = repo.get_document(db, user_id, doc_id)
    if doc:
        if doc["session_id"] != sid:
            raise HTTPException(404, "document not found")
        if doc["status"] != "failed":
            raise HTTPException(409, f"document is {doc['status']}")
    else:
        name = f"{doc_id}.{EXT[body.mime]}"
        if not repo.storage_exists(db, user_id, f"{user_id}/{sid}", name):
            raise HTTPException(400, "upload the file to storage first")
        doc = repo.add_document(
            db,
            user_id,
            sid,
            {
                "id": doc_id,
                "doc_type": body.doc_type,
                "storage_path": f"{user_id}/{sid}/{name}",
                "mime": body.mime,
                "quality": body.quality,
            },
        )
        repo.write_audit(db, user_id, sid, "document.uploaded", {"doc_type": body.doc_type}, "user")
    tasks.add_task(process_document, s, user_id, sid, doc_id)
    return {"document_id": doc_id, "status": "uploaded"}


class VaultIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    doc_type: Literal[DOC_TYPES]  # type: ignore[valid-type]


@router.post("/documents/from-vault", status_code=202)
def add_from_vault(
    session_id: UUID,
    body: VaultIn,
    tasks: BackgroundTasks,
    db: Db,
    user_id: UserId,
    s: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    """Reuses the file the user saved in their profile vault (<uid>/general/<type>/): copies it
    into this session and starts the pipeline, so nothing is asked twice. 404 if none saved."""
    _session(db, user_id, session_id)
    require_consent(db, user_id, "documents")
    sid, t = str(session_id), body.doc_type
    if any(d["doc_type"] == t for d in repo.list_documents(db, user_id, sid)):
        return {"status": "exists"}
    bucket = db.storage.from_(repo.BUCKET)
    folder = f"{user_id}/general/{t}"
    files = [f for f in bucket.list(folder) if f.get("id")]
    if not files:
        raise HTTPException(404, "nothing saved for this document")
    latest = max(files, key=lambda f: f.get("created_at") or "")
    ext = latest["name"].rsplit(".", 1)[-1].lower()
    mime = {v: k for k, v in EXT.items()}.get("jpg" if ext == "jpeg" else ext)
    if not mime:
        raise HTTPException(400, "unsupported file type")
    doc_id = str(uuid4())
    path = f"{user_id}/{sid}/{doc_id}.{EXT[mime]}"
    bucket.copy(f"{folder}/{latest['name']}", path)
    repo.add_document(
        db, user_id, sid, {"id": doc_id, "doc_type": t, "storage_path": path, "mime": mime}
    )
    repo.write_audit(db, user_id, sid, "document.reused", {"doc_type": t}, "user")
    tasks.add_task(process_document, s, user_id, sid, doc_id)
    return {"document_id": doc_id, "status": "uploaded"}


class ResolveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidate_id: UUID | None = None
    value: str | None = Field(default=None, max_length=200)
    reason: str = Field(min_length=3, max_length=300)


class AcknowledgeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=3, max_length=300)


def _resolve(db: Any, user_id: str, session_id: UUID, flag_id: UUID, **kw: Any) -> dict[str, Any]:
    _session(db, user_id, session_id)
    try:
        flag = resolve(db, user_id, str(session_id), str(flag_id), **kw)
    except ResolveError as e:
        raise HTTPException(409 if "already" in str(e) else 400, str(e)) from None
    return {"flag_id": flag["id"], "status": flag["status"]}


@router.post("/flags/{flag_id}/resolve")
def resolve_flag(
    session_id: UUID, flag_id: UUID, body: ResolveIn, db: Db, user_id: UserId
) -> dict[str, Any]:
    """Pick a candidate or type a value (+ reason) -> confirmed value; neither -> acknowledged."""
    return _resolve(
        db,
        user_id,
        session_id,
        flag_id,
        reason=body.reason,
        via="tap",  # voice answers go through the resolve_flag tool, with their message id
        candidate_id=str(body.candidate_id) if body.candidate_id else None,
        value=body.value,
    )


@router.post("/flags/{flag_id}/acknowledge")
def acknowledge_flag(
    session_id: UUID, flag_id: UUID, body: AcknowledgeIn, db: Db, user_id: UserId
) -> dict[str, Any]:
    return _resolve(db, user_id, session_id, flag_id, reason=body.reason, via="tap")


@router.get("/audit")
def get_audit(session_id: UUID, db: Db, user_id: UserId) -> dict[str, Any]:
    """This session's audit trail with the hash chain recomputed (app/audit.py)."""
    _session(db, user_id, session_id)
    rows = fetch_audit(db, user_id=user_id, session_id=str(session_id))
    broken = verify_chain(rows)
    events = [
        {k: r[k] for k in ("id", "actor", "action", "hash")}
        | {"payload": json.loads(r["payload_text"] or "null"), "created_at": r["created_text"]}
        for r in rows
    ]
    return {"events": events, "verified": not broken, "broken": broken}


@router.get("/readiness")
def get_readiness(session_id: UUID, db: Db, user_id: UserId) -> dict[str, Any]:
    """The readiness payload (values the form will use + sources): the /fill page's field list."""
    return readiness(db, user_id, _session(db, user_id, session_id))
