"""Per-document pipeline (VERIFICATION.md): download -> pages -> OCR lines -> extract -> validate ->
field_values candidates. Runs as a background task after POST /documents; progress is the
documents.status column (uploaded -> processing -> extracted | failed)."""

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from app.config import Settings
from app.db import supabase as repo
from app.llm.client import LLMUnavailable
from app.verify import names
from app.verify.extraction import EXPECTED, extract
from app.verify.ocr import NO_VISION_FALLBACK, OcrUnavailable, read_lines, render
from app.verify.validator import KIND, check

log = logging.getLogger(__name__)
LOW_CONFIDENCE = 0.6

DOC_LABELS = {
    "aadhaar": "Aadhaar card",
    "ssc_marksheet": "Class 10 marksheet",
    "hsc_marksheet": "Class 12 marksheet",
    "income_certificate": "Income certificate",
    "caste_certificate": "Caste certificate",
    "caste_validity": "Caste validity certificate",
    "domicile_certificate": "Domicile certificate",
    "bank_passbook": "Bank passbook",
    "fee_receipt": "Fee receipt",
    "admission_letter": "Admission letter",
    "gap_certificate": "Gap certificate",
    "other": "Other document",
}


def field_label(key: str) -> str:
    return key.replace("_", " ").replace("ssc", "10th").replace("hsc", "12th").capitalize()


def normalized_value(field_key: str, value: str) -> str:
    return names.normalized(value) if KIND.get(field_key) == "name" else value.strip().casefold()


async def _db(fn: Callable[..., Any], *a: Any) -> Any:
    return await asyncio.to_thread(fn, *a)


async def process_document(s: Settings, user_id: str, session_id: str, document_id: str) -> None:
    """Never raises: failures end in status=failed with a short error code."""
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
    except Exception:
        log.exception("document pipeline failed")  # no document content in logs
        err = "internal"
    else:
        return
    await _db(repo.update_document, db, user_id, document_id, {"status": "failed", "error": err})


async def _run(s: Settings, db: Any, user_id: str, session_id: str, doc: dict[str, Any]) -> None:
    doc_type = doc["doc_type"]
    bucket = db.storage.from_(repo.BUCKET)
    data = await _db(bucket.download, doc["storage_path"])
    pages = await _db(render, data, doc["mime"])
    lines, engine = await read_lines(s, pages, doc_type, user_id, session_id)

    folder = doc["storage_path"].rsplit(".", 1)[0]  # <uid>/<sid>/<document_id>
    page_meta = []
    for i, p in enumerate(pages):
        path = f"{folder}/p{i + 1}.png"
        opts = {"content-type": "image/png", "upsert": "true"}
        await _db(bucket.upload, path, p.png, opts)
        page_meta.append({"path": path, "width": p.width, "height": p.height})
    if doc_type in NO_VISION_FALLBACK:
        # Guardrail 6: the upload holds the full number; only the masked pages are kept.
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
