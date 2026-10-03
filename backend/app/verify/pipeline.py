"""Per-document pipeline (VERIFICATION.md): download -> pages -> OCR lines -> extract -> validate ->
field_values candidates. Runs as a background task after POST /documents; progress is the
documents.status column (uploaded -> processing -> extracted | failed)."""

import asyncio
import logging
import re
from collections.abc import Callable
from typing import Any

import httpx
from storage3.exceptions import StorageApiError

from app.config import Settings
from app.db import supabase as repo
from app.llm.client import LLMUnavailable
from app.verify import names
from app.verify.checks import run_checks
from app.verify.extraction import DOC_LABELS, EXPECTED, extract, field_label
from app.verify.ocr import NO_VISION_FALLBACK, OcrUnavailable, Page, read_lines, render
from app.verify.validator import KIND, check

log = logging.getLogger(__name__)
LOW_CONFIDENCE = 0.6


def normalized_value(field_key: str, value: str) -> str:
    return names.normalized(value) if KIND.get(field_key) == "name" else value.strip().casefold()


async def _db(fn: Callable[..., Any], *a: Any) -> Any:
    """One retry on a dropped connection (the Supabase client's idle HTTP/2 connection is closed
    after a few quiet minutes; seen live) or a Storage 5xx."""
    try:
        return await asyncio.to_thread(fn, *a)
    except (httpx.TransportError, StorageApiError) as e:
        # Storage 5xx came back once mid-demo-run (Cloudflare error page); a 4xx is not retried.
        if isinstance(e, StorageApiError) and not str(e.status).startswith("5"):
            raise
        log.warning("db call retried after %s", type(e).__name__)
        return await asyncio.to_thread(fn, *a)


# The open conversation hears when a document is done, from the server, not from the browser's
# poll (seen live: no "document read" event ever arrived, so no cards and no summary).
# ponytail: in-process, one backend instance; a shared bus (Realtime/Redis) if it ever scales out.
_listeners: dict[str, set[Callable[[str], None]]] = {}


def subscribe(session_id: str, cb: Callable[[str], None]) -> Callable[[], None]:
    _listeners.setdefault(session_id, set()).add(cb)
    return lambda: _listeners.get(session_id, set()).discard(cb)


def _notify(session_id: str, document_id: str) -> None:
    for cb in list(_listeners.get(session_id, ())):
        try:
            cb(document_id)
        except Exception:
            log.exception("document listener failed")


async def process_document(s: Settings, user_id: str, session_id: str, document_id: str) -> None:
    """Never raises: failures end in status=failed with a short error code. Listeners of the
    session are told when it ends either way."""
    db = repo.get_db()
    doc = await _db(repo.get_document, db, user_id, document_id)
    if not doc or doc["session_id"] != session_id:
        return
    await _db(
        repo.update_document, db, user_id, document_id, {"status": "processing", "error": None}
    )
    try:
        await _run(s, db, user_id, session_id, doc)
    except OcrUnavailable:
        err = "ocr_unavailable"
    except LLMUnavailable:
        err = "llm_unavailable"
    except Exception as e:
        log.exception("document pipeline failed")  # no document content in logs
        err = f"internal:{type(e).__name__}"
    else:
        err = None
    if err:
        await _db(
            repo.update_document, db, user_id, document_id, {"status": "failed", "error": err}
        )
    _notify(session_id, document_id)


def _stored_pages(bucket: Any, folder: str) -> list[Page]:
    names = sorted(f["name"] for f in bucket.list(folder) if re.fullmatch(r"p\d+\.png", f["name"]))
    return [render(bucket.download(f"{folder}/{n}"), "image/png")[0] for n in names]


async def _run(s: Settings, db: Any, user_id: str, session_id: str, doc: dict[str, Any]) -> None:
    doc_type = doc["doc_type"]
    bucket = db.storage.from_(repo.BUCKET)
    folder = doc["storage_path"].rsplit(".", 1)[0]  # <uid>/<sid>/<document_id>
    try:
        data = await _db(bucket.download, doc["storage_path"])
        pages = await _db(render, data, doc["mime"])
    except StorageApiError:
        # A retry after the original was deleted (it held a full ID number): read the masked
        # pages kept from the first attempt.
        pages = await _db(_stored_pages, bucket, folder)
        if not pages:
            raise
    lines, engine = await read_lines(s, pages, doc_type, user_id, session_id)

    page_meta = []
    for i, p in enumerate(pages):
        path = f"{folder}/p{i + 1}.png"
        opts = {"content-type": "image/png", "upsert": "true"}
        await _db(bucket.upload, path, p.png, opts)
        page_meta.append({"path": path, "width": p.width, "height": p.height})
    if doc_type in NO_VISION_FALLBACK or any(p.masked for p in pages):
        # Guardrail 6: the upload holds a full ID number; only the masked pages are kept.
        await _db(bucket.remove, [doc["storage_path"]])

    items = await extract(s, doc_type, lines, user_id, session_id)
    by_id = {ln["id"]: ln for ln in lines}
    seen: set[str] = set()
    failed = []
    for it in items:
        if it.field_key in seen:
            continue
        c = check(it.field_key, it.value_text, it.line_ids, lines)
        if not c.ok:
            failed.append({"field_key": it.field_key, "reason": c.reason})
            continue
        seen.add(it.field_key)
        cited = [by_id[i] for i in it.line_ids]
        await _db(
            repo.add_field_value,
            db,
            user_id,
            session_id,
            {
                "field_key": it.field_key,
                "value": c.value,
                "value_normalized": normalized_value(it.field_key, c.value),
                "source_type": "document",
                "source_ref": {
                    "document_id": doc["id"],
                    "doc_type": doc_type,
                    "line_ids": it.line_ids,
                    "page": cited[0]["page"],
                    "bbox": [ln["bbox"] for ln in cited],
                },
                "confidence": c.confidence,
                "status": "candidate",
            },
        )
    missing = [k for k in EXPECTED.get(doc_type, ()) if k not in seen]
    ocr = {
        "engine": engine,
        "pages": page_meta,
        "lines": lines,
        "failed": failed,
        "missing": missing,
    }
    # Flags are written before the status flips, so the client's "read" event sees them.
    try:
        session = await _db(repo.get_session, db, user_id, session_id)
        await asyncio.to_thread(
            run_checks, db, user_id, session, include_missing=False, just_read=doc["id"]
        )
    except Exception:
        log.exception("checks after extraction failed")  # the document itself was read
    await _db(
        repo.update_document,
        db,
        user_id,
        doc["id"],
        {"status": "extracted", "ocr": ocr, "page_count": len(pages)},
    )


def review_payload(doc: dict[str, Any], fields: list[dict[str, Any]]) -> dict[str, Any]:
    """field_review card: every value with its source (guardrail 2)."""
    ocr = doc.get("ocr") or {}
    own = [f for f in fields if (f.get("source_ref") or {}).get("document_id") == doc["id"]]
    return {
        "document_id": doc["id"],
        "doc_type": doc["doc_type"],
        "label": DOC_LABELS.get(doc["doc_type"], doc["doc_type"]),
        "status": doc["status"],
        "error": doc.get("error"),
        "engine": ocr.get("engine"),
        "pages": ocr.get("pages", []),
        "fields": [
            {
                "id": f["id"],
                "field_key": f["field_key"],
                "label": field_label(f["field_key"]),
                "value": f["value"],
                "confidence": f.get("confidence"),
                "low_confidence": (f.get("confidence") or 0) < LOW_CONFIDENCE,
                "source": f["source_ref"],
            }
            for f in own
        ],
        "unreadable": [field_label(x["field_key"]) for x in ocr.get("failed", [])],
    }
