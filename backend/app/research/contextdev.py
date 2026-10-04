"""Context.dev (docs.context.dev, checked 2026-10-04): the one module that calls it.

- POST /web/search: the search fallback after Tavily, with each result's page as Markdown.
- POST /web/scrape: a real browser reads a page our fetch.py could not (a 403 from a bot wall, a
  JS-only page, a scanned PDF while the GPU OCR is off).
Only public URLs and scheme-name queries are sent, never student data. Calls cost credits: tests
mock this module. Retries: a 429 waits Retry-After once (<= 5 s); 408/5xx once after 1 s; other
4xx never. Logs carry the status and request_id only, never page text."""

import logging
import time
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.config import Settings
from app.llm.client import Breaker
from app.research.fetch import FetchError, Page

log = logging.getLogger(__name__)
breaker = Breaker()
MAX_RETRY_AFTER_S = 5.0


class ContextDevUnavailable(Exception):
    """Message is safe to show the LLM/user."""


def enabled(s: Settings) -> bool:
    return bool(s.context_dev_api_key)


def _post(s: Settings, path: str, body: dict[str, Any]) -> dict[str, Any]:
    if not enabled(s):
        raise ContextDevUnavailable("Context.dev is not configured")
    if not breaker.ok():
        raise ContextDevUnavailable("Context.dev is temporarily unavailable")
    headers = {"Authorization": f"Bearer {s.context_dev_api_key}"}
    for attempt in range(2):
        try:
            r = httpx.post(
                f"{s.context_dev_base_url}{path}",
                headers=headers,
                json=body,
                timeout=s.context_dev_timeout_s,
            )
        except httpx.HTTPError as e:
            log.warning("context.dev %s failed: %s", path, type(e).__name__)
            if attempt == 0:
                time.sleep(1)
                continue
            breaker.failure()
            raise ContextDevUnavailable("could not reach Context.dev") from e
        rid = r.headers.get("x-request-id") or ""
        if r.status_code == 200:
            breaker.success()
            data = r.json()
            log.info("context.dev %s ok request_id=%s", path, data.get("request_id") or rid)
            return data
        # A 4xx body describes our request (validation), never page text: worth logging.
        why = r.text[:300] if 400 <= r.status_code < 500 else ""
        log.warning("context.dev %s HTTP %s request_id=%s %s", path, r.status_code, rid, why)
        wait = r.headers.get("retry-after", "")
        if (
            r.status_code == 429
            and attempt == 0
            and wait.replace(".", "", 1).isdigit()
            and float(wait) <= MAX_RETRY_AFTER_S
        ):
            time.sleep(float(wait))
            continue
        if r.status_code in (408, 500, 502, 503, 504) and attempt == 0:
            time.sleep(1)
            continue
        if r.status_code >= 500 or r.status_code in (408, 429):
            breaker.failure()  # busy or broken; a 4xx is our request, not their outage
        raise ContextDevUnavailable(f"Context.dev answered HTTP {r.status_code}")
    raise ContextDevUnavailable("Context.dev did not answer")  # unreachable: the loop returns


def search(
    s: Settings, query: str, include_domains: list[str] | None = None, n: int = 10
) -> list[dict[str, Any]]:
    """-> [{title, url, snippet, text}] (text = the page as Markdown, "" if it was not read)."""
    body: dict[str, Any] = {
        "query": query,
        "numResults": max(10, n),  # the API's minimum
        "country": "in",
        "markdownOptions": {
            "enabled": True,
            "maxAgeMs": s.context_dev_max_age_ms,
            # whole page: MahaDBT keeps the eligibility text outside the "main content" guess
            "useMainContentOnly": False,
            "includeLinks": False,
            "pdf": {"shouldParse": True},
        },
    }
    if include_domains:
        body["includeDomains"] = include_domains[:100]
    out = []
    for x in _post(s, "/web/search", body).get("results") or []:
        md = x.get("markdown") or {}
        out.append(
            {
                "title": (x.get("title") or "")[:200],
                "url": x.get("url") or "",
                "snippet": (x.get("description") or "")[:300],
                "text": (md.get("markdown") or "") if md.get("code") == "SUCCESS" else "",
            }
        )
    return [x for x in out if x["url"]]


def scrape(s: Settings, url: str) -> Page:
    """A page read by Context.dev's browser (PDFs OCR'd when they are scans)."""
    if urlsplit(url).scheme not in ("http", "https"):
        raise FetchError("only http(s) links can be read")
    body = {
        "url": url,
        "formats": {"markdown": True},
        "markdownParams": {"includeLinks": False, "includeImages": False},
        "maxAgeMs": s.context_dev_max_age_ms,
        "sharedParams": {"parsers": {"pdf": {"ocr": "auto"}}},  # scanned PDFs are OCR'd
        "timeoutOpts": {"milliseconds": 20_000, "behavior": "return-partial"},
    }
    try:
        data = _post(s, "/web/scrape", body)
    except ContextDevUnavailable as e:
        raise FetchError(str(e)) from e
    md = data.get("markdown") or {}
    text = " ".join((md.get("data") or "").split())
    if not md.get("success") or not text:
        raise FetchError("no readable text on that page")
    title = ((data.get("metadata") or {}).get("title") or "")[:300]
    return Page(url=data.get("url") or url, title=title, text=text, notes=["read via Context.dev"])
