"""Web search: Tavily (POST /search, Bearer key; docs.tavily.com, checked 2026-10-04), then
Context.dev when Tavily is down or found nothing official (find()). Both return each page's text
with the results, so the one-step research needs no second download for most pages."""

import logging
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.config import Settings
from app.llm.client import Breaker
from app.research import contextdev

log = logging.getLogger(__name__)
breaker = Breaker()
OFFICIAL_SUFFIXES = (".gov.in", ".nic.in")


class SearchUnavailable(Exception):
    pass


def official(url: str, prefer: list[str] | None = None) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    doms = [d.lower().lstrip("*.") for d in prefer or []]
    if host.endswith(OFFICIAL_SUFFIXES):
        return True
    return any(host == d or host.endswith("." + d) for d in doms)


def search(
    s: Settings, query: str, prefer_domains: list[str] | None = None, max_results: int = 6
) -> list[dict[str, Any]]:
    """-> [{title, url, snippet, official}], official/preferred domains first."""
    if not s.tavily_api_key:
        raise SearchUnavailable("search is not configured")
    if not breaker.ok():
        raise SearchUnavailable("search is temporarily unavailable")
    body: dict[str, Any] = {
        "query": query,
        "max_results": max_results,
        "search_depth": "basic",
        "include_raw_content": "text",  # the page itself, for research_scheme
    }
    # Tavily answers 400 to "*.gov.in" in prefer mode (seen live; the model writes wildcards).
    doms = sorted({d.strip().lower().removeprefix("*.") for d in prefer_domains or [] if d.strip()})
    if doms:
        body |= {"include_domains": doms, "include_domains_mode": "prefer"}
    try:
        r = httpx.post(
            f"{s.tavily_base_url}/search",
            headers={"Authorization": f"Bearer {s.tavily_api_key}"},
            json=body,
            timeout=s.search_timeout_s,
        )
        r.raise_for_status()
        results = r.json().get("results") or []
    except (httpx.HTTPError, ValueError) as e:
        breaker.failure()
        log.warning("tavily failed: %s", type(e).__name__)
        raise SearchUnavailable("search failed") from e
    breaker.success()
    out = [
        {
            "title": (x.get("title") or "")[:200],
            "url": x.get("url") or "",
            "snippet": (x.get("content") or "")[:300],
            "official": official(x.get("url") or "", prefer_domains),
            "text": x.get("raw_content") or "",
        }
        for x in results
        if x.get("url")
    ]
    return sorted(out, key=lambda x: not x["official"])  # stable: keeps Tavily's order otherwise


def find(s: Settings, query: str, prefer_domains: list[str] | None = None) -> list[dict[str, Any]]:
    """Tavily, then Context.dev when Tavily failed or found nothing official. Raises
    SearchUnavailable only when neither could search."""
    results: list[dict[str, Any]] = []
    error: SearchUnavailable | None = None
    try:
        results = search(s, query, prefer_domains)
    except SearchUnavailable as e:
        error = e
    if any(r["official"] for r in results) or not contextdev.enabled(s):
        if error:
            raise error
        return results
    try:
        more = contextdev.search(s, query)  # no includeDomains: a preference, not a filter
    except contextdev.ContextDevUnavailable as e:
        if error:
            raise error from e
        return results
    seen = {r["url"] for r in results}
    extra = [
        {**x, "official": official(x["url"], prefer_domains)} for x in more if x["url"] not in seen
    ]
    return sorted(results + extra, key=lambda x: not x["official"])
