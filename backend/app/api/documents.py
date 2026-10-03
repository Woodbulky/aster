"""Documents (VERIFICATION.md). The client uploads to Storage <uid>/<sid>/<document_id>.<ext>
(storage RLS: own folder only), then calls this; all table writes stay on the backend."""

from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.config import Settings, get_settings
from app.db import supabase as repo
from app.deps import Db, UserId
from app.research.packs import DOC_TYPES
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
