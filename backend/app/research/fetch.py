"""Download a web page or PDF and turn it into plain text (RESEARCH.md "Live research").

URLs come from search results and web pages, i.e. untrusted input (guardrail 8), so every hop is
checked: http(s) only, and the host must resolve to a public address (no localhost, private or
link-local ranges). Bodies are capped in size and time."""

import ipaddress
import re
import socket
import time
import unicodedata
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit

import httpx
import trafilatura

from app.config import Settings
from app.research.pdf import pdf_text

UA = {"User-Agent": "Mozilla/5.0 (compatible; AsterResearch/0.1; scholarship eligibility lookup)"}
MAX_REDIRECTS = 5
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)


class FetchError(Exception):
    """Message is safe to show the LLM/user."""


@dataclass
class Page:
    url: str  # final URL after redirects
    title: str
    text: str  # whitespace-collapsed
    notes: list[str] = field(default_factory=list)


def check_url(url: str) -> None:
    u = urlsplit(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        raise FetchError("only http(s) links can be read")
    try:
        infos = socket.getaddrinfo(u.hostname, u.port or (443 if u.scheme == "https" else 80))
    except (socket.gaierror, UnicodeError) as e:
        raise FetchError("site not found") from e
    # ponytail: DNS is re-resolved by httpx (rebinding window); pin the IP if this ever matters.
    for info in infos:
        if not ipaddress.ip_address(info[4][0]).is_global:
            raise FetchError("that address is not allowed")


def download(s: Settings, url: str) -> tuple[str, str, bytes, str | None]:
    """-> (final url, content type, body, charset). Follows redirects by hand so each hop is
    checked."""
    # The httpx timeout is per read: a server dripping bytes kept a PDF going for 55 s (seen
    # live). The deadline caps the whole download.
    deadline = time.monotonic() + s.fetch_total_s
    with httpx.Client(timeout=s.fetch_timeout_s, headers=UA, follow_redirects=False) as c:
        for _ in range(MAX_REDIRECTS + 1):
            check_url(url)
            try:
                with c.stream("GET", url) as r:
                    if r.is_redirect:
                        url = urljoin(url, r.headers.get("location", ""))
                        continue
                    if r.status_code >= 400:
                        raise FetchError(f"the site answered HTTP {r.status_code}")
                    body = bytearray()
                    for chunk in r.iter_bytes():
                        body += chunk
                        if len(body) > s.fetch_max_bytes:
                            raise FetchError("the page is too large to read")
                        if time.monotonic() > deadline:
                            raise FetchError("the site is too slow to read")
                    ctype = r.headers.get("content-type", "")
                    return str(r.url), ctype, bytes(body), r.charset_encoding
            except httpx.HTTPError as e:
                raise FetchError(f"could not reach the site ({type(e).__name__})") from e
    raise FetchError("too many redirects")


def fetch(s: Settings, url: str) -> Page:
    if "://" not in url:  # models pass "site.org/page" (seen live); check_url still applies
        url = "https://" + url.lstrip("/")
    final, ctype, body, charset = download(s, url)
    if "pdf" in ctype.lower() or body[:5] == b"%PDF-":
        try:
            text, notes = pdf_text(s, body)
        except Exception as e:  # pymupdf raises its own types on broken files
            raise FetchError("the PDF could not be read") from e
        title = urlsplit(final).path.rsplit("/", 1)[-1]
    else:
        html = body.decode(charset or "utf-8", errors="replace")
        m = _TITLE.search(html)
        title = " ".join(m.group(1).split()) if m else ""
        # html2txt keeps the whole page: trafilatura's main-content guess picked a hidden modal
        # table on mahadbt.maharashtra.gov.in scheme pages and dropped the eligibility section.
        text, notes = trafilatura.html2txt(html) or "", []
    text = " ".join(text.split())
    if not text:
        raise FetchError("no readable text on that page")
    return Page(url=final, title=title[:300], text=text, notes=notes)


DEFAULT_FOCUS = (
    "eligib income criteria document certificate required domicile category marks percentage "
    "पात्र उत्पन्न कागदपत्र प्रमाणपत्र अट दस्तावेज आय योग्यता"
)


def excerpt(text: str, focus: str | None = None, limit: int = 2100, size: int = 700) -> str:
    """The parts of a long page most about `focus`, in page order. Government pages put ~7k chars
    of menus before the scheme text, so the first N chars are useless to the LLM."""
    if len(text) <= limit:
        return text
    terms = [t.casefold() for t in (focus or DEFAULT_FOCUS).split()]
    chunks = [text[i : i + size] for i in range(0, len(text), size)]
    low = [c.casefold() for c in chunks]
    # Count each term at most twice per chunk: a menu repeating "Eligibility Calculator" must not
    # beat the one paragraph that mentions eligibility, income and the scheme's name.
    ranked = sorted(range(len(chunks)), key=lambda i: -sum(min(low[i].count(t), 2) for t in terms))
    return " … ".join(chunks[i] for i in sorted(ranked[: limit // size]))


_PUNCT = str.maketrans({"‘": "'", "’": "'", "‚": "'", "′": "'", "“": '"', "”": '"', "„": '"',
                        "–": "-", "—": "-", "―": "-", "‐": "-", " ": " "})  # fmt: skip


def norm(text: str) -> str:
    """For quote matching: NFKC, plain quotes/dashes, casefolded, whitespace collapsed."""
    return " ".join(unicodedata.normalize("NFKC", text).translate(_PUNCT).casefold().split())


def quote_in(quote: str, text: str) -> bool:
    return bool(norm(quote)) and norm(quote) in norm(text)
