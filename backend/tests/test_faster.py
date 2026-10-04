"""Faster research and faster turns: one-step research (pages read side by side), the Context.dev
fallbacks (always mocked: real calls cost credits), research shared across students, parallel
lookups, obvious intents run in code, and conversation going to brain_primary first."""

import json
import time

import httpx
import pytest

from app.agent import orchestrator
from app.agent.tools import ToolResult, run_tool
from app.agent.tools import research as research_tools
from app.config import Settings
from app.db import supabase as repo
from app.research import contextdev, search
from app.research.fetch import FetchError, Page
from tests.conftest import COMPLETE_PROFILE, FakeStore
from tests.test_agent import FakeLLM, call, ctx, text
from tests.test_research import PAGE_TEXT, PAGE_URL, _item

KEY = Settings(_env_file=None, context_dev_api_key="ctxt_test")


@pytest.fixture
def ctxdev(monkeypatch: pytest.MonkeyPatch) -> "Seen":
    """Context.dev on, its HTTP mocked; -> the requests it got. Set .replies to queue answers."""
    monkeypatch.setattr(contextdev, "enabled", lambda s: bool(s.context_dev_api_key))
    monkeypatch.setattr(contextdev.time, "sleep", lambda s: None)
    seen = Seen()
    replies = seen.replies

    def post(url, headers, json, timeout):
        seen.append({"url": url, "auth": headers["Authorization"], "body": json})
        r = replies.pop(0)
        r.request = httpx.Request("POST", url)
        return r

    monkeypatch.setattr(contextdev.httpx, "post", post)
    return seen


class Seen(list):
    """The requests Context.dev got; .replies = the answers it will give, in order."""

    def __init__(self) -> None:
        super().__init__()
        self.replies: list[httpx.Response] = []


# ---------- the Context.dev wrapper ----------
def test_scrape_request_and_page(ctxdev) -> None:
    ctxdev.replies.append(
        httpx.Response(
            200,
            json={
                "url": "https://x.gov.in/scheme",
                "markdown": {
                    "requested": True,
                    "success": True,
                    "data": "# Rules\n\nIncome  below 2.5 lakh",
                },
                "metadata": {"title": "Scheme"},
                "request_id": "r1",
            },
        )
    )
    page = contextdev.scrape(KEY, "https://x.gov.in/scheme")
    assert (page.url, page.title, page.text) == (
        "https://x.gov.in/scheme",
        "Scheme",
        "# Rules Income below 2.5 lakh",
    )
    assert page.notes == ["read via Context.dev"]
    req = ctxdev[0]
    assert (
        req["url"] == "https://api.context.dev/v1/web/scrape" and req["auth"] == "Bearer ctxt_test"
    )
    assert req["body"]["formats"] == {"markdown": True}
    assert req["body"]["sharedParams"] == {"parsers": {"pdf": {"ocr": "auto"}}}  # scans OCR'd
    assert req["body"]["maxAgeMs"] == 604_800_000
    with pytest.raises(FetchError):
        contextdev.scrape(KEY, "file:///etc/passwd")
    assert len(ctxdev) == 1  # never sent


def test_retries_follow_the_rules(ctxdev) -> None:
    ok = httpx.Response(200, json={"results": []})
    ctxdev.replies += [httpx.Response(429, headers={"retry-after": "2"}), ok]
    assert contextdev.search(KEY, "q") == []  # waited 2 s once, then served
    ctxdev.replies += [httpx.Response(429, headers={"retry-after": "60"})]
    with pytest.raises(contextdev.ContextDevUnavailable):
        contextdev.search(KEY, "q")  # too long to wait inside a turn
    ctxdev.replies += [httpx.Response(400)]
    with pytest.raises(contextdev.ContextDevUnavailable, match="400"):
        contextdev.search(KEY, "q")
    assert len(ctxdev) == 4  # the 60 s 429 and the 400 were not retried
    ctxdev.replies += [httpx.Response(503), httpx.Response(200, json={"results": []})]
    assert contextdev.search(KEY, "q") == []  # a 5xx is retried once


def test_breaker_and_disabled(ctxdev) -> None:
    for _ in range(3):
        ctxdev.replies += [httpx.Response(500), httpx.Response(500)]
        with pytest.raises(contextdev.ContextDevUnavailable):
            contextdev.search(KEY, "q")
    with pytest.raises(contextdev.ContextDevUnavailable, match="temporarily"):
        contextdev.search(KEY, "q")  # open for 60 s: no request
    assert len(ctxdev) == 6
    with pytest.raises(contextdev.ContextDevUnavailable, match="not configured"):
        contextdev.search(Settings(_env_file=None), "q")


# ---------- the chains ----------
def test_search_falls_back_to_context_dev(monkeypatch: pytest.MonkeyPatch, ctxdev) -> None:
    monkeypatch.setattr(
        search, "search", lambda *a, **k: (_ for _ in ()).throw(search.SearchUnavailable("down"))
    )
    ctxdev.replies.append(
        httpx.Response(
            200,
            json={
                "results": [
                    {
                        "url": "https://blog.example/x",
                        "title": "Blog",
                        "description": "d",
                        "markdown": {"code": "NOT_REQUESTED"},
                    },
                    {
                        "url": "https://scholarships.gov.in/x",
                        "title": "NSP",
                        "markdown": {"markdown": "Eligibility text", "code": "SUCCESS"},
                    },
                ]
            },
        )
    )
    out = search.find(KEY, "nsp scholarship")
    assert [(r["title"], r["official"], r["text"]) for r in out] == [
        ("NSP", True, "Eligibility text"),
        ("Blog", False, ""),
    ]
    assert ctxdev[0]["body"]["markdownOptions"]["enabled"] is True
    ctxdev.replies.append(httpx.Response(500))
    ctxdev.replies.append(httpx.Response(500))
    with pytest.raises(search.SearchUnavailable, match="down"):
        search.find(KEY, "nsp")  # both down: the plain error


def test_official_tavily_results_need_no_second_search(
    monkeypatch: pytest.MonkeyPatch, ctxdev
) -> None:
    gov = {"title": "Gov", "url": "https://x.gov.in", "official": True, "text": "t"}
    monkeypatch.setattr(search, "search", lambda *a, **k: [gov])
    assert search.find(KEY, "q") == [gov] and ctxdev == []


def test_tavily_asks_for_the_page_text(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = {}

    def post(url, headers, json, timeout):
        seen.update(json)
        res = [{"title": "Gov", "url": "https://x.gov.in", "content": "s", "raw_content": "page"}]
        return httpx.Response(200, json={"results": res}, request=httpx.Request("POST", url))

    monkeypatch.setattr(search.httpx, "post", post)
    out = search.search(Settings(_env_file=None, tavily_api_key="k"), "q")
    assert seen["include_raw_content"] == "text" and out[0]["text"] == "page"


def test_page_chain(monkeypatch: pytest.MonkeyPatch) -> None:
    on = Settings(_env_file=None, context_dev_api_key="k")
    monkeypatch.setattr(contextdev, "enabled", lambda s: bool(s.context_dev_api_key))
    scraped = []

    def scrape(s, url):
        scraped.append(url)
        return Page(url=url, title="T", text="from the browser " * 50)

    monkeypatch.setattr(contextdev, "scrape", scrape)

    def blocked(s, url):
        raise FetchError("the site answered HTTP 403")

    monkeypatch.setattr(research_tools, "fetch", blocked)
    assert research_tools.read_page(on, "https://a.gov.in").text.startswith("from the browser")
    with pytest.raises(FetchError, match="403"):  # Context.dev off: the first reason
        research_tools.read_page(Settings(_env_file=None), "https://a.gov.in")
    monkeypatch.setattr(
        research_tools, "fetch", lambda s, url: Page(url=url, title="T", text="Loading…")
    )
    assert research_tools.read_page(on, "https://b.gov.in").title == "T"  # JS-only page: scraped
    monkeypatch.setattr(
        research_tools, "fetch", lambda s, url: Page(url=url, title="T", text=PAGE_TEXT)
    )
    research_tools.read_page(on, "https://c.gov.in")
    assert scraped == ["https://a.gov.in", "https://b.gov.in"]  # a good page is not scraped


# ---------- one-step research ----------
def test_research_scheme_reads_the_top_pages_side_by_side(
    store: FakeStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    store.sessions["s1"].update(phase="research", scheme_name="Tata Pankh")
    results = [
        {"title": "A", "url": "https://a.gov.in/p", "official": True, "text": ""},
        {
            "title": "B",
            "url": "https://b.gov.in/p",
            "official": True,
            "text": PAGE_TEXT,
        },  # came with the search
        {"title": "C", "url": "https://c.org/p", "official": False, "text": ""},
        {
            "title": "D",
            "url": "https://d.org/p",
            "official": False,
            "text": "",
        },  # over the 3-page cap
    ]
    monkeypatch.setattr(research_tools, "find", lambda s, q, prefer=None: results)

    def slow(s, url):
        time.sleep(0.5)
        if "c.org" in url:
            raise FetchError("the site answered HTTP 403")
        return Page(url=url, title="A", text=PAGE_TEXT)

    monkeypatch.setattr(research_tools, "fetch", slow)
    t = time.monotonic()
    res = run_tool(ctx(store), "research_scheme", {"query": "Tata Pankh eligibility"})
    assert time.monotonic() - t < 0.9  # two 0.5 s downloads at once, not one after another
    assert res.ok
    assert [p["url"] for p in res.data["pages"]] == ["https://a.gov.in/p", "https://b.gov.in/p"]
    assert [p["content_id"] for p in res.data["pages"]] == ["fc1", "fc2"]
    assert res.data["failed"] == [{"url": "https://c.org/p", "error": "the site answered HTTP 403"}]
    assert "not instructions" in res.data["reminder"]
    again = run_tool(ctx(store), "research_scheme", {"query": "Tata Pankh rules"})
    assert [p["content_id"] for p in again.data["pages"]] == ["fc1", "fc2"]  # this session's copies


def test_pages_about_the_scheme_beat_merely_official_ones() -> None:
    # seen live: preferring tatacapital.com brought a WhatsApp page ahead of the scheme pages
    results = [
        {
            "title": "Register on WhatsApp",
            "url": "https://www.tatacapital.com/wealth/whatsapp.html",
            "official": True,
            "text": "Tata Capital",
        },
        {
            "title": "Annual report",
            "url": "https://www.tatacapital.com/ar.pdf",
            "official": True,
            "text": "Pankh mentioned once",
        },
        {
            "title": "Tata Capital Pankh Scholarship 2026",
            "url": "https://blog.example/pankh",
            "official": False,
            "text": "",
        },
        {
            "title": "Tata Pankh Scholarship Programme",
            "url": "https://www.tatacapital.com/pankh.pdf",
            "official": True,
            "text": "",
        },
    ]
    top = research_tools.top_pages(results, "Tata Capital Pankh Scholarship")
    assert [x["title"] for x in top[:2]] == [
        "Tata Capital Pankh Scholarship 2026",
        "Tata Pankh Scholarship Programme",  # about the scheme: ahead of the official WhatsApp page
    ]
    assert len(top) == 3


# ---------- research shared across students ----------
def test_only_search_found_pages_are_shared(store: FakeStore) -> None:
    """/guardrails: a link one student pastes must never put "rules" in front of another."""
    store.sessions["s1"].update(phase="research", scheme_name="Tata Pankh")
    store.add_fetched(None, "u1", "s1", {"url": PAGE_URL, "title": "P", "text": PAGE_TEXT})
    assert run_tool(ctx(store), "save_research", {"items": [_item()]}).ok  # saved for them
    assert store.research and store.cache == []  # but not shared: fetched from a named link
    other = "https://scholarships.example.gov.in/faq"
    store.add_fetched(
        None, "u1", "s1", {"url": other, "title": "F", "text": PAGE_TEXT, "via": "search"}
    )
    said = _item(content_id="fc2", source_url=other, text="Aadhaar 1234 5678 9012 is needed")
    assert run_tool(ctx(store), "save_research", {"items": [said]}).ok
    [row] = store.cache
    assert row["items"]["eligibility"][0]["text"] == "Aadhaar [number ending 9012] is needed"
    assert row["items"]["documents"] == []


def test_research_scheme_pages_are_marked_as_found_by_search(
    store: FakeStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    store.sessions["s1"].update(phase="research", scheme_name="Tata Pankh")
    found = [{"title": "Pankh", "url": PAGE_URL, "official": True, "text": PAGE_TEXT}]
    monkeypatch.setattr(research_tools, "find", lambda s, q, prefer=None: found)
    assert run_tool(ctx(store), "research_scheme", {"query": "Tata Pankh"}).ok
    monkeypatch.setattr(
        research_tools, "fetch", lambda s, url: Page(url=url, title="X", text=PAGE_TEXT)
    )
    assert run_tool(ctx(store), "fetch_url", {"url": "https://pasted.example/x"}).ok
    assert [f["via"] for f in store.fetched] == ["search", "link"]


def test_saved_research_is_reused_by_the_next_student(
    store: FakeStore, run, monkeypatch: pytest.MonkeyPatch
) -> None:
    store.sessions["s1"].update(phase="research", scheme_name="Tata Pankh")
    page = {"url": PAGE_URL, "title": "P", "text": PAGE_TEXT, "via": "search"}
    store.add_fetched(None, "u1", "s1", page)
    assert run_tool(ctx(store), "save_research", {"items": [_item()]}).ok
    [row] = store.cache
    assert row["scheme_norm"] == "tata pankh"
    assert "content_id" not in row["items"]["eligibility"][0]  # that row was the first student's
    # a new session names the same scheme: no research rounds at all
    store.profile.update(COMPLETE_PROFILE)
    store.sessions["s1"] = {"id": "s1", "user_id": "u1", "phase": "choose_form", "portal": None}
    store.research.clear()
    llm = FakeLLM(
        call("set_form", {"scheme_name": "Tata Pankh"}), text("I found its rules earlier.")
    )
    sent = run(llm, user_text="Tata Pankh scholarship please")
    assert [m.phase for m in sent if m.type == "phase"] == ["research", "eligibility"]
    assert [m.kind for m in sent if m.type == "card"] == ["research_summary"]
    assert len(llm.calls) == 2  # set_form, then the reply: no search, no page reads
    assert {(r["kind"], r["origin"]) for r in store.research} == {("eligibility", "live")}
    assert ("research.reused", {"scheme": "Tata Pankh"}) in store.audit


def test_expired_or_unlike_names_are_not_reused(store: FakeStore) -> None:
    store.cache.append(
        {
            "scheme_norm": "tata pankh",
            "scheme_name": "Tata Pankh",
            "items": {},
            "saved_at": "2026-01-01",
            "expires_at": "2026-01-31T00:00:00+00:00",
        }
    )
    assert research_tools.cached_research(ctx(store), "Tata Pankh") is None  # expired
    store.cache[0]["expires_at"] = "2999-01-01T00:00:00+00:00"
    assert research_tools.cached_research(ctx(store), "tata  PANKH")
    assert research_tools.cached_research(ctx(store), "HDFC Badhte Kadam") is None


# ---------- faster turns ----------
def test_lookups_in_one_round_run_side_by_side(
    store: FakeStore, run, monkeypatch: pytest.MonkeyPatch
) -> None:
    store.sessions["s1"].update(phase="research", scheme_name="Tata Pankh")

    def slow(s, url):
        time.sleep(0.5)
        return Page(url=url, title="P", text=PAGE_TEXT)

    monkeypatch.setattr(research_tools, "fetch", slow)
    two = [
        {
            "index": 0,
            "id": "a",
            "function": {"name": "fetch_url", "arguments": json.dumps({"url": "https://a.gov.in"})},
        },
        {
            "index": 1,
            "id": "b",
            "function": {"name": "fetch_url", "arguments": json.dumps({"url": "https://b.gov.in"})},
        },
    ]
    from app.llm.client import Chunk

    llm = FakeLLM(
        [Chunk("fallback", {"tool_calls": two})],
        text("Found nothing."),
        text("Found nothing."),
        text("ok"),
    )
    t = time.monotonic()
    run(llm, user_text="Tata Pankh")
    assert time.monotonic() - t < 0.9
    tool_msgs = [m for m in llm.calls[1]["messages"] if m["role"] == "tool"]
    assert [m["tool_call_id"] for m in tool_msgs] == ["a", "b"]  # the order the model asked in
    assert [json.loads(m["content"])["data"]["url"] for m in tool_msgs] == [
        "https://a.gov.in",
        "https://b.gov.in",
    ]


@pytest.mark.parametrize("said", ["I'm done uploading", "सगळं तपासा", "हो गया, सब चेक करो", "done"])
def test_done_uploading_runs_the_checks_in_code(
    store: FakeStore, run, monkeypatch: pytest.MonkeyPatch, said: str
) -> None:
    store.sessions["s1"].update(phase="documents", scheme_key="demo.obc_aid")
    ran = []

    async def tool_ui(c, send, name, args):
        ran.append(name)
        return ToolResult(ok=True, data={"checked": True})

    async def no_cards(c, send):
        return []

    monkeypatch.setattr(orchestrator, "run_tool_ui", tool_ui)
    monkeypatch.setattr(orchestrator, "show_new_flag_cards", no_cards)
    monkeypatch.setattr(repo, "list_flags", lambda *a, **k: [])
    llm = FakeLLM(text("I checked everything."))
    run(llm, user_text=said)
    assert ran == ["run_verification"] and len(llm.calls) == 1
    assert any(m.get("tool_calls") for m in llm.calls[0]["messages"])  # it sees the code's call


def test_a_long_message_is_not_a_done_signal(
    store: FakeStore, run, monkeypatch: pytest.MonkeyPatch
) -> None:
    store.sessions["s1"].update(phase="documents", scheme_key="demo.obc_aid")
    monkeypatch.setattr(repo, "list_flags", lambda *a, **k: [])
    llm = FakeLLM(text("Sure."))
    run(
        llm, user_text="I have done my 12th from Pune and want to know which documents I still need"
    )
    assert not any(m.get("tool_calls") for m in llm.calls[0]["messages"])


def test_conversation_prefers_the_brain_primary(store: FakeStore, run) -> None:
    seen = []

    async def llm(_s, messages, *, tools=None, **kw):
        seen.append(kw.get("prefer"))
        for ch in text("hi"):
            yield ch

    run(llm, user_text="hello")
    assert seen == ["fallback"]  # Groq first by default (BRAIN_PRIMARY)


def test_flag_answers_prefer_the_brain_primary(monkeypatch: pytest.MonkeyPatch) -> None:
    # It runs before every reply in the flag phases: GPU-first added ~3-5 s to each one.
    import asyncio

    from app.agent import answers
    from app.llm.client import Chunk

    seen: list[dict] = []

    async def llm(_s, _msgs, **kw):
        seen.append(kw)
        yield Chunk("fallback", {"content": '{"answers": []}'})

    monkeypatch.setattr(answers, "chat_stream", llm)
    flag = {"id": "f1", "details": {"field_label": "Income", "candidates": []}}
    asyncio.run(answers.read_answers(Settings(_env_file=None), [flag], "ok", "", "u1", "s1"))
    assert seen[0]["prefer"] == "fallback"
    assert seen[0]["sensitive_kind"] == "flag_answer"  # a Groq call is still audited


def test_already_read_pages_are_in_the_prompt(store: FakeStore, run) -> None:
    store.sessions["s1"].update(phase="research", scheme_name="Tata Pankh")
    store.add_fetched(None, "u1", "s1", {"url": PAGE_URL, "title": "P", "text": PAGE_TEXT})
    llm = FakeLLM(text("ok"), text("ok"), text("ok"))
    run(llm, user_text="go on")
    assert f'"url": "{PAGE_URL}", "content_id": "fc1"' in llm.calls[0]["messages"][0]["content"]


# ---------- research -> a draft pack for the team ----------
def test_promoted_research_is_a_valid_draft_pack() -> None:
    from app.research.packs import Pack
    from scripts.promote_research import draft_pack

    item = {"source_url": PAGE_URL, "quote": "passed Class 12 with at least 60% marks"}
    row = {
        "scheme_name": "Tata Capital Pankh Scholarship",
        "saved_at": "2026-10-04T10:00:00+00:00",
        "items": {
            "eligibility": [{**item, "text": "12th with 60%"}],
            "documents": [
                {**item, "text": "Income certificate from the Tahsildar"},
                {**item, "text": "Two photos"},
            ],
        },
    }
    pack = Pack.model_validate(draft_pack(row, "other"))
    assert pack.scheme_key == "other.tata_capital_pankh_scholarship" and pack.status == "draft"
    assert pack.criteria[0].logic is None  # a reviewer writes the rule
    assert [d.doc_type for d in pack.documents] == ["income_certificate", "other"]
    assert pack.official_urls == [PAGE_URL]


def test_thinking_is_sent_before_any_db_write(
    store: FakeStore, run, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent = run(text("hi"), user_text="hello")
    first = sent[0]
    assert first.type == "agent_state" and first.state == "thinking"
    user = [m for m in store.messages if m["role"] == "user"]
    assert user[0]["content"] == "hello"  # still stored, with its id kept for the turn
