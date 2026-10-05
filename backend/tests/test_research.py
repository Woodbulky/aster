import json
import socket
from pathlib import Path

import httpx
import pymupdf
import pytest

from app.agent.tools import research as research_tools
from app.agent.tools import run_tool
from app.config import Settings
from app.research import fetch as fetch_mod
from app.research import packs, search
from app.research.fetch import FetchError, Page, check_url, excerpt, quote_in
from app.verify import requirements
from tests.conftest import COMPLETE_PROFILE, FakeStore
from tests.test_agent import FakeLLM, call, ctx, kinds, text

PAGE_URL = "https://scholarships.example.gov.in/pankh"
PAGE_TEXT = (
    "Home About Contact "
    * 20
    + "Eligibility: The applicant must have passed Class 12 with at least 60% marks. "
    "Annual family income must be less than Rs. 4,00,000 from all sources. "
    "Documents: Income certificate issued by the Tahsildar. "
)


# ---------- fetch: SSRF guard ----------
def _resolve(monkeypatch: pytest.MonkeyPatch, table: dict[str, str]) -> None:
    def fake(host, port, *a, **k):
        if host not in table:
            raise socket.gaierror("nope")
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (table[host], port))]

    monkeypatch.setattr(fetch_mod.socket, "getaddrinfo", fake)


@pytest.mark.parametrize(
    "url,ip",
    [
        ("http://localhost/x", "127.0.0.1"),
        ("http://intranet.example/x", "10.0.0.5"),
        ("http://metadata.example/latest", "169.254.169.254"),
        ("http://router.example/", "192.168.1.1"),
        ("http://v6.example/", "::1"),
    ],
)
def test_check_url_blocks_internal(monkeypatch: pytest.MonkeyPatch, url: str, ip: str) -> None:
    _resolve(monkeypatch, {url.split("/")[2]: ip})
    with pytest.raises(FetchError, match="not allowed"):
        check_url(url)


def test_check_url_schemes(monkeypatch: pytest.MonkeyPatch) -> None:
    _resolve(monkeypatch, {"ok.example": "93.184.216.34"})
    check_url("https://ok.example/page")  # public: fine
    for bad in ("file:///etc/passwd", "ftp://ok.example/x", "javascript:alert(1)"):
        with pytest.raises(FetchError, match="only http"):
            check_url(bad)
    with pytest.raises(FetchError, match="not found"):
        check_url("https://missing.example/")


def _serve(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    real = httpx.Client
    monkeypatch.setattr(
        fetch_mod.httpx,
        "Client",
        lambda **kw: real(transport=httpx.MockTransport(handler), **kw),
    )


def test_redirect_to_internal_is_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    _resolve(monkeypatch, {"ok.example": "93.184.216.34", "evil.example": "127.0.0.1"})
    _serve(
        monkeypatch,
        lambda req: httpx.Response(302, headers={"location": "http://evil.example/admin"}),
    )
    with pytest.raises(FetchError, match="not allowed"):
        fetch_mod.fetch(Settings(), "https://ok.example/start")


def test_fetch_html_pdf_and_size_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    _resolve(monkeypatch, {"ok.example": "93.184.216.34"})
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "Family income up to Rs. 2.50 lakh per annum.")
    pdf = doc.tobytes()
    html = (
        "<html><head><title>Scheme  page</title><script>var x=1</script></head><body>"
        "<nav>Menu</nav><p>Eligibility: resident of\n   Maharashtra.</p></body></html>"
    )

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith(".pdf"):
            return httpx.Response(200, content=pdf, headers={"content-type": "application/pdf"})
        if req.url.path == "/big":
            return httpx.Response(200, content=b"x" * 2000, headers={"content-type": "text/html"})
        return httpx.Response(200, text=html, headers={"content-type": "text/html"})

    _serve(monkeypatch, handler)
    page = fetch_mod.fetch(Settings(), "https://ok.example/scheme")
    assert page.title == "Scheme page"
    assert "Eligibility: resident of Maharashtra." in page.text  # whitespace collapsed
    assert "var x" not in page.text
    page = fetch_mod.fetch(Settings(), "https://ok.example/gr.pdf")
    assert "Family income up to Rs. 2.50 lakh per annum." in page.text
    with pytest.raises(FetchError, match="too large"):
        fetch_mod.fetch(Settings(fetch_max_bytes=1000), "https://ok.example/big")


def test_slow_site_hits_the_total_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    _resolve(monkeypatch, {"ok.example": "93.184.216.34"})
    clock = iter(range(0, 1000, 15))  # every look at the clock: 15 s later
    monkeypatch.setattr(fetch_mod.time, "monotonic", lambda: next(clock))

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=iter([b"<p>a</p>"] * 5), headers={"content-type": "text/html"}
        )

    _serve(monkeypatch, handler)
    with pytest.raises(FetchError, match="too slow"):
        fetch_mod.fetch(Settings(), "https://ok.example/slow")


def test_scanned_pdf_page_without_gpu_is_noted(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.research.pdf import pdf_text

    monkeypatch.setattr("app.research.pdf.gpu_url", lambda s: None)
    doc = pymupdf.open()
    doc.new_page()  # no text layer: looks like a scan
    text, notes = pdf_text(Settings(), doc.tobytes())
    assert text.strip() == "" and notes == ["page 1 is a scan and OCR is unavailable"]


def test_excerpt_finds_the_scheme_text() -> None:
    long = "Menu item. " * 600 + "Eligibility: family income below 2.5 lakh. " + "Footer. " * 300
    out = excerpt(long)
    assert "Eligibility: family income below 2.5 lakh." in out.replace(" … ", "")
    assert len(out) < 2300
    assert excerpt("short page") == "short page"


def test_quote_normalisation() -> None:
    page = "Family Declaration Certificate about two children’s.  Rs.\n2,50,000"
    assert quote_in("family declaration certificate about two children's.", page)
    assert quote_in("Rs. 2,50,000", page)
    assert not quote_in("Rs. 3,50,000", page)
    assert not quote_in("   ", page)


# ---------- search ----------
def test_search_ranks_official_first(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = {}

    def post(url, headers, json, timeout):
        seen.update(json)
        results = [
            {"title": "Blog", "url": "https://buddy.example/pankh", "content": "x"},
            {"title": "Owner", "url": "https://www.tatacapital.com/pankh", "content": "y"},
            {"title": "Gov", "url": "https://mahadbt.maharashtra.gov.in/x", "content": "z"},
        ]
        return httpx.Response(200, json={"results": results}, request=httpx.Request("POST", url))

    monkeypatch.setattr(search.httpx, "post", post)
    out = search.search(Settings(tavily_api_key="k"), "pankh", ["*.tatacapital.com"])
    assert seen["include_domains"] == ["tatacapital.com"]  # Tavily rejects "*." (HTTP 400)
    assert [r["title"] for r in out] == ["Owner", "Gov", "Blog"]
    assert seen["include_domains_mode"] == "prefer"
    with pytest.raises(search.SearchUnavailable):
        search.search(Settings(tavily_api_key=""), "pankh")


def test_search_breaker(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def post(*a, **k):
        calls.append(1)
        raise httpx.ConnectTimeout("slow")

    monkeypatch.setattr(search.httpx, "post", post)
    for _ in range(4):
        with pytest.raises(search.SearchUnavailable):
            search.search(Settings(tavily_api_key="k"), "q")
    assert len(calls) == 3  # the 4th call is skipped for 60 s


# ---------- packs ----------
def test_real_packs_parse() -> None:
    """The real knowledge/ packs (not the test fixtures) all pass the offline checks."""
    real = Path(__file__).resolve().parents[2] / "knowledge"
    packs.KNOWLEDGE = real  # restored by the autouse fixture
    packs.all_packs.cache_clear()
    packs.portals.cache_clear()
    assert packs.validate(online=False) == []
    assert len(packs.all_packs()) >= 7
    assert {"mahadbt", "lic", "nsp"} <= set(packs.portals())


@pytest.mark.parametrize(
    "change,error",
    [
        ({"status": "verified", "verified_by": None}, "verified_by"),
        ({"scheme_key": "other.obc_aid"}, "must start with"),
        (
            {"criteria": [{"id": "x", "text": {"en": "x"}, "logic": {"==": [{"var": "income"}, 1]},
                           "source": {"url": "https://a.gov.in", "quote": "long enough"}}]},
            "unknown variables",
        ),
        (
            {"criteria": [{"id": "x", "text": {"en": "x"}, "logic": {"regex": [1, 1]},
                           "source": {"url": "https://a.gov.in", "quote": "long enough"}}]},
            "unsupported operator",
        ),
        ({"documents": [{"doc_type": "passport", "required": True, "text": {"en": "x"},
                         "source": {"url": "https://a.gov.in", "quote": "long enough"}}]},
         "doc_type"),
    ],
)  # fmt: skip
def test_pack_validation(change: dict, error: str) -> None:
    base = json.loads(
        (Path(__file__).parent / "fixtures/knowledge/demo/obc_aid.json").read_text("utf-8")
    )
    with pytest.raises(ValueError, match=error):
        packs.Pack.model_validate({**base, **change})


def test_drafts_only_in_dev() -> None:
    # _env_file=None: a developer's .env with PACKS_INCLUDE_DRAFT=true must not change the test
    assert set(packs.usable_packs(Settings(_env_file=None))) == {"demo.obc_aid", "demo.open_merit"}
    assert "demo.draft_one" in packs.usable_packs(Settings(packs_include_draft=True))
    assert "demo.draft_one" not in packs.usable_packs(
        Settings(packs_include_draft=True, app_env="prod")
    )


def test_verified_packs_are_for_this_cycle_only() -> None:
    # Last year's rules are not offered as verified: the student would follow the wrong year.
    assert packs.usable_packs(Settings(_env_file=None, academic_year="2027-28")) == {}
    pack = packs.all_packs()["demo.obc_aid"]
    with pytest.raises(ValueError, match="academic_year, apply_url"):
        packs.Pack.model_validate(pack.model_dump() | {"apply_url": None})


def test_freshness_clocks() -> None:
    from datetime import date

    pack = packs.all_packs()["demo.obc_aid"]  # rules + deadlines checked 2026-10-03
    s = Settings(_env_file=None)
    f = packs.freshness(pack, s, date(2026, 10, 10))
    assert (f["rules_stale"], f["deadlines_stale"]) == (False, False)
    f = packs.freshness(pack, s, date(2026, 11, 1))  # deadlines are rechecked every 14 days
    assert (f["rules_stale"], f["deadlines_stale"]) == (False, True)
    f = packs.freshness(pack, s, date(2027, 5, 1))  # rules every 180
    assert f["rules_stale"] and f["rules_checked_on"] == "2026-10-03"
    draft = packs.all_packs()["demo.draft_one"]
    assert packs.freshness(draft, s)["rules_stale"]  # never checked


def test_portal_url_per_cycle() -> None:
    src = {
        "url": "https://mahadbt.maharashtra.gov.in/home/index",
        "quote": "Applications for 2026-27",
    }
    cyc = {"url": "https://mahadbt2.maharashtra.gov.in/", "source": src}
    p = packs.Portal(name="M", url="https://mahadbt.maharashtra.gov.in", cycles={"2026-27": cyc})
    assert p.url_for("2026-27") == "https://mahadbt2.maharashtra.gov.in/"
    assert p.url_for("2025-26") == "https://mahadbt.maharashtra.gov.in"


def test_validate_checks_the_cycle_of_verified_packs(monkeypatch: pytest.MonkeyPatch) -> None:
    assert packs.validate(online=False) == []
    monkeypatch.setenv("ACADEMIC_YEAR", "2027-28")
    problems = packs.validate(online=False)
    assert any("verified for 2026-27, not 2027-28" in p for p in problems)


# ---------- eligibility ----------
def test_check_eligibility_card(store: FakeStore) -> None:
    store.profile.update(COMPLETE_PROFILE)
    store.sessions["s1"].update(phase="eligibility", scheme_key="demo.obc_aid")
    res = run_tool(ctx(store, "en"), "check_eligibility", {})
    p = res.card.payload
    assert res.card.kind == "eligibility" and p["origin"] == "pack" and not p["draft"]
    by_id = {r["id"]: r for r in p["results"]}
    assert by_id["obc"]["reason"] == "Meets this — per scholarships.demo.gov.in"
    assert by_id["domicile"]["status"] == "unknown"
    assert by_id["domicile"]["ask_field"] == "domicile_state"
    assert by_id["attendance"]["reason"].startswith("Needs confirmation — Aster can't check this")
    assert by_id["attendance"]["needs"] == [{"kind": "read", "text": "75% attendance"}]
    assert by_id["obc"]["source"]["quote"] == "Applicant should belong to OBC category."
    assert p["counts"] == {"met": 2, "not_met": 0, "unknown": 2, "not_applicable": 0}
    assert p["deadlines"][0]["passed"] is True
    # guardrail 1: no final verdict anywhere in what the user or the LLM sees
    blob = json.dumps([p, res.data["criteria"]]).lower()
    assert "you are eligible" not in blob and "not eligible" not in blob
    store.profile["annual_family_income"] = 300000
    p = run_tool(ctx(store, "en"), "check_eligibility", {}).card.payload
    assert {r["id"]: r["status"] for r in p["results"]}["income"] == "not_met"


# ---------- live research: the quote validator ----------
@pytest.fixture
def page(store: FakeStore) -> dict:
    store.sessions["s1"].update(phase="research", scheme_name="Tata Pankh")
    return store.add_fetched(None, "u1", "s1", {"url": PAGE_URL, "title": "P", "text": PAGE_TEXT})


def _item(**kw) -> dict:
    return {
        "kind": "eligibility",
        "text": "12th with 60%",
        "source_url": PAGE_URL,
        "quote": "passed Class 12 with at least 60% marks",
        "content_id": "fc1",
    } | kw


def test_save_research_keeps_quoted_items(store: FakeStore, page: dict) -> None:
    items = [
        _item(),
        _item(kind="documents", text="Income certificate", quote="Income certificate issued by "
              "the Tahsildar."),
    ]  # fmt: skip
    res = run_tool(ctx(store), "save_research", {"items": items})
    assert res.ok and res.data["saved"] == {"eligibility": 1, "documents": 1}
    assert res.card.kind == "research_summary"
    item = res.card.payload["eligibility"][0]
    assert item["site"] == "scholarships.example.gov.in" and item["fetched_on"] == "2026-10-03"
    assert "Unverified" in res.card.payload["note"]
    assert {(r["kind"], r["origin"], r["scheme"]) for r in store.research} == {
        ("eligibility", "live", "Tata Pankh"),
        ("documents", "live", "Tata Pankh"),
    }


def test_saved_documents_are_requirements_and_years_must_be_on_the_page(
    store: FakeStore, page: dict
) -> None:
    quote = "Income certificate issued by the Tahsildar."
    page["via"] = "search"  # shared with later students
    items = [
        _item(year_on_page="2026-27"),  # the page states no year: dropped, not believed
        _item(kind="documents", text="Income certificate", quote=quote, required="if",
              condition="your parents are salaried, form 1234 5678 9012",
              doc_types=["income_certificate"]),
    ]  # fmt: skip
    res = run_tool(ctx(store), "save_research", {"items": items})
    assert "year_on_page" not in res.card.payload["eligibility"][0]
    doc = res.card.payload["documents"][0]
    assert (doc["required"], doc["doc_types"]) == ("if", ["income_certificate"])
    [r] = requirements.from_live([doc], "2026-27")
    # the model's own words go through redact_ids before other students see them
    shared = store.cache[0]["items"]["documents"][0]["condition"]
    assert "1234 5678" not in shared and shared.startswith("your parents are salaried")
    assert r.questions[0]["text"].startswith("Does this apply to you? Only if: your parents")

    store.add_fetched(None, "u1", "s1", {"url": PAGE_URL + "/old", "title": "P",
                                         "text": PAGE_TEXT + " Scheme for 2025-26."})  # fmt: skip
    old = _item(content_id="fc2", source_url=PAGE_URL + "/old", year_on_page="2025-26")
    item = run_tool(ctx(store), "save_research", {"items": [old]}).card.payload["eligibility"][0]
    assert item["year_on_page"] == "2025-26"
    assert "the page is about 2025-26, not 2026-27" in requirements.year_note(item, "2026-27")


@pytest.mark.parametrize(
    "today,cycle",
    [("2026-10-05", "2026-27"), ("2027-05-31", "2026-27"), ("2027-06-01", "2027-28")],
)
def test_current_cycle(today: str, cycle: str) -> None:
    from datetime import date

    by_date = Settings(_env_file=None, academic_year="")  # conftest pins ACADEMIC_YEAR
    assert packs.current_cycle(by_date, date.fromisoformat(today)) == cycle
    assert packs.current_cycle(Settings(_env_file=None, academic_year="2025-26")) == "2025-26"


@pytest.mark.parametrize(
    "bad,why",
    [
        # the acceptance test: a fabricated quote is rejected
        ({"quote": "Annual family income must be less than Rs. 8,00,000"}, "not found"),
        ({"quote": "Students of all categories can apply without income limit."}, "not found"),
        ({"source_url": "https://other.gov.in/rules"}, "source_url must be"),  # misattributed
        ({"quote": "60% marks"}, "shorter than"),  # too short to prove anything
        ({"content_id": "fc999"}, "not found in this session"),
    ],
)
def test_save_research_rejects(store: FakeStore, page: dict, bad: dict, why: str) -> None:
    res = run_tool(ctx(store), "save_research", {"items": [_item(**bad)]})
    assert not res.ok and why in res.data[0]["why"]
    assert store.research == []


def test_save_research_mixed_keeps_only_good(store: FakeStore, page: dict) -> None:
    items = [_item(), _item(text="made up", quote="Only girls from Pune may apply for this.")]
    res = run_tool(ctx(store), "save_research", {"items": items})
    assert res.ok and res.data["saved"]["eligibility"] == 1
    assert [r["text"] for r in res.data["rejected"]] == ["made up"]
    assert [i["text"] for i in store.research[0]["items"]] == ["12th with 60%"]


def test_save_research_other_sessions_content(store: FakeStore, page: dict) -> None:
    store.sessions["s2"] = {"id": "s2", "user_id": "u1", "phase": "research", "scheme_name": "X"}
    c = ctx(store)
    c.session = store.sessions["s2"]
    assert not run_tool(c, "save_research", {"items": [_item()]}).ok


def test_live_research_turn(store: FakeStore, run, monkeypatch: pytest.MonkeyPatch) -> None:
    """Unknown scheme: search -> fetch -> save_research (quote-checked) -> eligibility card with
    every live criterion unknown/unverified."""
    store.profile.update(COMPLETE_PROFILE)
    store.sessions["s1"].update(phase="research", scheme_name="Tata Pankh")
    monkeypatch.setattr(
        research_tools,
        "find",
        lambda s, q, prefer=None: [{"title": "Pankh", "url": PAGE_URL, "official": True}],
    )
    monkeypatch.setattr(
        research_tools, "fetch", lambda s, url: Page(url=url, title="Pankh", text=PAGE_TEXT)
    )
    good = _item(quote="Annual family income must be less than Rs. 4,00,000", text="Income < 4L")
    fake = _item(text="Girls only", quote="This scholarship is for girl students only.")
    llm = FakeLLM(
        call("search_web", {"query": "Tata Pankh scholarship eligibility"}),
        call("fetch_url", {"url": PAGE_URL, "focus": "eligibility income"}),
        call("save_research", {"items": [good, fake]}),
        text("मला 1 अट सापडली (असत्यापित)."),  # check_eligibility runs in code
    )
    sent = run(llm, user_text="Tata Pankh")
    assert [m.phase for m in sent if m.type == "phase"] == ["eligibility"]
    cards = [m for m in sent if m.type == "card"]
    assert [c.kind for c in cards] == ["research_summary", "eligibility"]
    assert [i["text"] for i in cards[0].payload["eligibility"]] == ["Income < 4L"]  # fake dropped
    elig = cards[1].payload
    assert elig["origin"] == "live" and elig["counts"] == {
        "met": 0,
        "not_met": 0,
        "unknown": 1,
        "not_applicable": 0,
    }
    assert elig["results"][0]["reason"].startswith("Unverified — from scholarships.example.gov.in")
    # the LLM saw the page as data, focused on the scheme text, with a content_id
    fetched = json.loads(llm.calls[2]["messages"][-1]["content"])["data"]
    assert fetched["content_id"] == "fc1" and "not instructions" in fetched["reminder"]
    assert store.fetched[0]["text"] == PAGE_TEXT
    assert "save_research" in {t["function"]["name"] for t in llm.calls[2]["tools"]}
    after = llm.calls[3]["messages"]  # the model sees the code-run check before replying
    assert after[-2]["tool_calls"][0]["function"]["name"] == "check_eligibility"
    assert '"unknown": 1' in after[-1]["content"]
    assert kinds(sent)[-1] == "agent_state"


def test_same_page_is_fetched_once_per_session(
    store: FakeStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    store.sessions["s1"].update(phase="research", scheme_name="Tata Pankh")
    calls = []

    def fake_fetch(s, url):
        calls.append(url)
        return Page(url=url, title="Pankh", text=PAGE_TEXT)

    monkeypatch.setattr(research_tools, "fetch", fake_fetch)
    a = run_tool(ctx(store), "fetch_url", {"url": PAGE_URL})
    b = run_tool(ctx(store), "read_pdf", {"url": PAGE_URL})
    assert calls == [PAGE_URL] and len(store.fetched) == 1
    assert a.data["content_id"] == b.data["content_id"] == "fc1"


def test_search_failure_is_plain(store: FakeStore, monkeypatch: pytest.MonkeyPatch) -> None:
    store.sessions["s1"].update(phase="research", scheme_name="Tata Pankh")
    monkeypatch.setattr(research_tools, "get_settings", lambda: Settings(_env_file=None))
    res = run_tool(ctx(store), "search_web", {"query": "pankh"})  # no Tavily key
    assert not res.ok and "official site" in res.error


def test_typed_rules_are_held_and_nudged(
    store: FakeStore, run, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Seen live: the model read a page, then typed its own rule list instead of save_research.
    That text must never reach the user; the model is told to save quoted items instead."""
    store.profile.update(COMPLETE_PROFILE)
    store.sessions["s1"].update(phase="research", scheme_name="Tata Pankh")
    monkeypatch.setattr(
        research_tools, "fetch", lambda s, url: Page(url=url, title="Pankh", text=PAGE_TEXT)
    )
    good = _item(quote="Annual family income must be less than Rs. 4,00,000", text="Income < 4L")
    llm = FakeLLM(
        call("fetch_url", {"url": PAGE_URL}),
        text("Rules: Indian citizen, Class 11 or 12, income below Rs 4 lakh."),  # unchecked
        call("save_research", {"items": [good]}),
        text("I found 1 rule on scholarships.example.gov.in (unverified)."),
    )
    sent = run(llm, user_text="Tata Pankh")
    shown = "".join(m.text for m in sent if m.type == "assistant_delta")
    assert "Indian citizen" not in shown
    assert shown == "I found 1 rule on scholarships.example.gov.in (unverified)."
    assert "did not call save_research" in llm.calls[2]["messages"][-1]["content"]
    assert [m.kind for m in sent if m.type == "card"] == ["research_summary", "eligibility"]
    assert "Indian citizen" not in store.messages[-1]["content"]  # not stored either


def test_cap_reached_still_saves_once_and_hides_tool_markup(
    store: FakeStore, run, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Seen live (Groq): failed fetches used up the 6 tool calls; the model then typed
    "<tool_call><function=save_research>..." as text. The markup is hidden and one
    save_research past the cap is allowed, so the quotes it found are kept."""
    store.profile.update(COMPLETE_PROFILE)
    store.sessions["s1"].update(phase="research", scheme_name="Tata Pankh")
    monkeypatch.setattr(
        research_tools, "fetch", lambda s, url: Page(url=url, title="Pankh", text=PAGE_TEXT)
    )
    good = _item(quote="Annual family income must be less than Rs. 4,00,000", text="Income < 4L")
    llm = FakeLLM(
        *[call("fetch_url", {"url": PAGE_URL}) for _ in range(6)],
        text("Saving.\n<tool_call>\n<function=save_research>\n<parameter=items>[...]"),
        call("save_research", {"items": [good]}),
        text("I found 1 rule (unverified)."),
    )
    sent = run(llm, user_text="Tata Pankh")
    assert llm.calls[6]["tools"] is None  # the cap round
    assert [t["function"]["name"] for t in llm.calls[7]["tools"]] == ["save_research"]
    assert [m.kind for m in sent if m.type == "card"] == ["research_summary", "eligibility"]
    shown = "".join(m.text for m in sent if m.type == "assistant_delta")
    assert "<tool_call>" not in shown and "<tool_call>" not in store.messages[-1]["content"]


def test_research_narration_without_tools_is_held_and_nudged(
    store: FakeStore, run, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Seen live: the model copied "Let me check… Let me read…" from the history and called no
    tool. That text is not shown; the model is told to call the tool."""
    store.sessions["s1"].update(phase="research", scheme_name="Tata Pankh")
    monkeypatch.setattr(
        research_tools,
        "find",
        lambda s, q, prefer=None: [{"title": "Pankh", "url": PAGE_URL, "official": True}],
    )
    llm = FakeLLM(
        text("Let me check the official rules.\n\nLet me read the official page."),
        call("search_web", {"query": "Tata Pankh eligibility"}),
        text("I searched; reading the official page next."),
    )
    sent = run(llm, user_text="Tata Pankh")
    shown = "".join(m.text for m in sent if m.type == "assistant_delta")
    assert "Let me check" not in shown
    assert "called no tool" in llm.calls[1]["messages"][-1]["content"]
    assert [m.name for m in sent if m.type == "tool_event" and m.status == "done"] == ["search_web"]


def test_url_without_scheme_gets_https(monkeypatch: pytest.MonkeyPatch) -> None:
    _resolve(monkeypatch, {"ok.example": "93.184.216.34"})
    seen = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(str(req.url))
        return httpx.Response(
            200,
            text="<html><body><p>Eligibility: resident of Maharashtra.</p></body></html>",
            headers={"content-type": "text/html"},
        )

    _serve(monkeypatch, handler)
    fetch_mod.fetch(Settings(), "ok.example/scheme")
    assert seen == ["https://ok.example/scheme"]


def test_narration_after_a_search_is_nudged_too(
    store: FakeStore, run, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Seen live (GPU): search_web, then "Let me read the official page…" and no further tool."""
    store.sessions["s1"].update(phase="research", scheme_name="Tata Pankh")
    monkeypatch.setattr(
        research_tools,
        "find",
        lambda s, q, prefer=None: [{"title": "Pankh", "url": PAGE_URL, "official": True}],
    )
    monkeypatch.setattr(
        research_tools, "fetch", lambda s, url: Page(url=url, title="Pankh", text=PAGE_TEXT)
    )
    good = _item(quote="Annual family income must be less than Rs. 4,00,000", text="Income < 4L")
    llm = FakeLLM(
        call("search_web", {"query": "Tata Pankh eligibility"}),
        text("Let me read the official page for eligibility."),
        call("fetch_url", {"url": PAGE_URL}),
        text("Let me save that."),
        call("save_research", {"items": [good]}),
        text("I found 1 rule (unverified)."),
    )
    sent = run(llm, user_text="Tata Pankh")
    shown = "".join(m.text for m in sent if m.type == "assistant_delta")
    assert "Let me" not in shown and shown == "I found 1 rule (unverified)."
    assert [m.kind for m in sent if m.type == "card"] == ["research_summary", "eligibility"]
