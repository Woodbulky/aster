"""PDF -> text with pymupdf. Pages with no text layer (scans) go to the GPU /ocr when it is up."""

import logging

import httpx
import pymupdf

from app.config import Settings
from app.llm.client import gpu_url

log = logging.getLogger(__name__)
MIN_PAGE_CHARS = 40  # less text than this = a scanned page


def _ocr(s: Settings, png: bytes) -> str:
    # LLM_PRIMARY picks the brain only; OCR uses the worker whenever it is up.
    url = gpu_url(s.model_copy(update={"llm_primary": "gpu"}))
    if not url:
        return ""
    try:
        r = httpx.post(
            f"{url}/ocr",
            headers={"Authorization": f"Bearer {s.gateway_token}"},
            files={"file": ("page.png", png, "image/png")},
            timeout=s.ocr_timeout_s,
        )
        r.raise_for_status()
        return " ".join(line["text"] for line in r.json().get("lines", []))
    except (httpx.HTTPError, ValueError, KeyError) as e:
        log.warning("pdf ocr failed: %s", type(e).__name__)
        return ""


def pdf_text(s: Settings, data: bytes) -> tuple[str, list[str]]:
    """-> (text, notes about what could not be read)."""
    doc = pymupdf.open(stream=data, filetype="pdf")
    parts: list[str] = []
    notes: list[str] = []
    for i, page in enumerate(doc):
        if i >= s.pdf_max_pages:
            notes.append(f"only the first {s.pdf_max_pages} of {doc.page_count} pages were read")
            break
        text = page.get_text()
        if len(text.strip()) < MIN_PAGE_CHARS:
            text = _ocr(s, page.get_pixmap(dpi=150).tobytes("png"))
            if not text:
                notes.append(f"page {i + 1} is a scan and OCR is unavailable")
        parts.append(text)
    return "\n".join(parts), notes
