"""Eligibility follows the education path and the scheme's own conditions (RESEARCH.md
"Eligibility evaluation"): answers, "not applicable", path-aware 12th, exact "needs"."""

from typing import Any

import pytest
from pydantic import ValidationError

from app.agent.tools import eligibility, run_tool
from app.agent.tools.eligibility import evaluate_pack
from app.research.packs import Pack
from app.verify import checks
from tests.conftest import COMPLETE_PROFILE, FakeStore
from tests.test_agent import ctx

SRC = {"url": "https://scholarships.demo.gov.in/x", "quote": "The rule as the page words it."}
INCOME = {"var": "profile.annual_family_income"}
PROFESSIONAL = {"==": [{"var": "answers.professional_course"}, "yes"]}
NON_PROFESSIONAL = {"==": [{"var": "answers.professional_course"}, "no"]}
NOTE = {"en": "Only for professional courses"}


def pack(criteria: list[dict[str, Any]], questions: tuple[str, ...] = ()) -> Pack:
    return Pack.model_validate(
        {
            "scheme_key": "demo.path",
            "portal": "demo",
            "status": "draft",
            "academic_year": "2026-27",
            "name": {"en": "Path"},
            "department": "d",
            "official_urls": ["https://x.gov.in"],
            "summary": {"en": "s"},
            "criteria": [{"text": {"en": c["id"]}, "source": SRC} | c for c in criteria],
            "questions": [{"id": q, "text": {"en": f"{q}?"}} for q in questions],
        }
    )


def status(rows: list[dict[str, Any]]) -> dict[str, str]:
    return {r["id"]: r["status"] for r in rows}


def row(rows: list[dict[str, Any]], cid: str) -> dict[str, Any]:
    return next(r for r in rows if r["id"] == cid)


INCOME_SPLIT = pack(
    [
        {
            "id": "income_8",
            "logic": {"<=": [INCOME, 800000]},
            "applies_if": PROFESSIONAL,
            "applies_note": NOTE,
        },
        {
            "id": "income_1",
            "logic": {"<=": [INCOME, 100000]},
            "applies_if": NON_PROFESSIONAL,
            "applies_note": {"en": "Only for non-professional courses"},
        },
    ],
    ("professional_course",),
)


def test_a_limit_for_another_course_type_is_not_applicable() -> None:
    # Before: both limits were checked for everyone, so 5 lakh "met" the 8 lakh line for a
    # non-professional student. Now the answer decides which limit is the rule.
    profile = {"annual_family_income": 500000}
    rows = evaluate_pack(INCOME_SPLIT, profile, "en", {"professional_course": "no"})
    assert status(rows) == {"income_8": "not_applicable", "income_1": "not_met"}
    assert row(rows, "income_8")["reason"] == "Not applicable — Only for professional courses"
    rows = evaluate_pack(INCOME_SPLIT, profile, "en", {"professional_course": "yes"})
    assert status(rows) == {"income_8": "met", "income_1": "not_applicable"}


def test_unanswered_condition_is_named_exactly() -> None:
    rows = evaluate_pack(INCOME_SPLIT, {"annual_family_income": 500000}, "en")
    r = row(rows, "income_8")
    assert r["status"] == "unknown"  # never guessed
    assert r["needs"] == [
        {
            "kind": "question",
            "id": "professional_course",
            "text": "professional_course?",
            "options": ["yes", "no"],
        }
    ]
    assert r["reason"] == "Needs confirmation — professional_course?"
    assert r["ask_field"] is None  # a question, not a profile value
    # no income yet: the profile value is what is asked, once the guard is answered
    rows = evaluate_pack(INCOME_SPLIT, {}, "en", {"professional_course": "yes"})
    r = row(rows, "income_8")
    assert [n["kind"] for n in r["needs"]] == ["profile"]
    assert r["ask_field"] == "annual_family_income"
    assert r["reason"] == "Needs confirmation — your profile has no annual family income yet"


def test_counts_include_not_applicable() -> None:
    rows = evaluate_pack(
        INCOME_SPLIT, {"annual_family_income": 50000}, "en", {"professional_course": "no"}
    )
    assert eligibility.counts(rows) == {"met": 1, "not_met": 0, "unknown": 0, "not_applicable": 1}


FIRST_YEAR = pack(
    [
        {
            "id": "first_year",
            "logic": {
                "and": [
                    {"==": [{"var": "profile.admission_year"}, {"var": "computed.cycle_start"}]},
                    {"==": [{"var": "profile.current_year"}, 1]},
                ]
            },
        }
    ]
)


def test_first_year_needs_the_admission_cycle_not_just_the_year_of_study() -> None:
    # A first-year student admitted in 2025 (a repeater) is not "admitted in 2026-27".
    repeater = {"admission_year": 2025, "current_year": 1}
    assert status(evaluate_pack(FIRST_YEAR, repeater, "en")) == {"first_year": "not_met"}
    fresher = {"admission_year": 2026, "current_year": 1}
    assert status(evaluate_pack(FIRST_YEAR, fresher, "en")) == {"first_year": "met"}
    # the rule's own cycle (the pack's), not the session's
    assert status(evaluate_pack(FIRST_YEAR, fresher, "en", cycle="2027-28")) == {
        "first_year": "met"
    }
    r = row(evaluate_pack(FIRST_YEAR, {"current_year": 1}, "en"), "first_year")
    assert r["status"] == "unknown" and r["ask_field"] == "admission_year"


TWELFTH = pack(
    [
        {
            "id": "hsc_60",
            "logic": {">=": [{"var": "profile.hsc_percentage"}, 60]},
            "ask_if_unknown": {"field_key": "hsc_percentage"},
        },
        {
            "id": "passed_10",
            "logic": {
                "or": [
                    {"!!": [{"var": "profile.ssc_year"}]},
                    {"!!": [{"var": "profile.entry_qualification"}]},
                ]
            },
        },
    ]
)


def test_diploma_student_is_never_asked_for_12th_results() -> None:
    rows = evaluate_pack(TWELFTH, {"entry_qualification": "ssc"}, "en")
    r = row(rows, "hsc_60")
    assert r["status"] == "unknown" and r["ask_field"] is None  # not asked ...
    assert "don't apply on your path" in r["reason"]  # ... and not a verdict either
    assert r["needs"] == [{"kind": "read", "text": "hsc_60"}]  # read the rule for your route
    assert row(rows, "passed_10")["status"] == "met"  # the path itself proves 10th
    # on a path with a 12th it is asked as before
    rows = evaluate_pack(TWELFTH, {"entry_qualification": "hsc"}, "en")
    assert row(rows, "hsc_60")["ask_field"] == "hsc_percentage"
    # given anyway: compared like any value
    rows = evaluate_pack(TWELFTH, {"entry_qualification": "diploma", "hsc_percentage": 71}, "en")
    assert row(rows, "hsc_60")["status"] == "met"


def test_a_rule_that_cannot_be_checked_is_read_at_the_source() -> None:
    rows = evaluate_pack(pack([{"id": "attendance"}]), {}, "en")
    assert rows[0]["needs"] == [{"kind": "read", "text": "attendance"}]
    assert rows[0]["reason"].startswith("Needs confirmation — Aster can't check this")


def test_pack_validation_for_the_new_logic() -> None:
    with pytest.raises(ValidationError, match="unknown variables"):
        pack([{"id": "x", "logic": PROFESSIONAL}])  # question not declared
    with pytest.raises(ValidationError, match="applies_note"):
        pack([{"id": "x", "applies_if": PROFESSIONAL}], ("professional_course",))
    with pytest.raises(ValidationError, match="unknown variables"):
        pack([{"id": "x", "logic": {"==": [{"var": "computed.nope"}, 1]}}])
    pack([{"id": "x", "logic": {"==": [{"var": "computed.cycle_start"}, 2026]}}])


@pytest.fixture
def scheme(store: FakeStore, monkeypatch: pytest.MonkeyPatch) -> FakeStore:
    for mod in (eligibility, checks):
        monkeypatch.setattr(mod, "usable_packs", lambda: {"demo.path": INCOME_SPLIT})
    store.profile.update(COMPLETE_PROFILE)
    store.sessions["s1"].update(phase="eligibility", scheme_key="demo.path")
    return store


def test_answer_settles_the_criterion_and_points_at_the_users_message(scheme: FakeStore) -> None:
    c = ctx(scheme, "en")
    res = run_tool(c, "check_eligibility", {})
    assert status(res.card.payload["results"]) == {"income_8": "unknown", "income_1": "unknown"}
    assert res.data["criteria"][0]["needs"][0]["id"] == "professional_course"

    def answer(q: str, a: str, mid: str) -> None:
        checks.store_answer(
            None, "u1", c.session, q, a, source_type="text", message_id=mid, via="tap"
        )

    answer("professional_course", "No", "m7")
    value = scheme.field_values[-1]
    assert (value["field_key"], value["value"], value["status"]) == (
        "answers.professional_course",
        "no",
        "confirmed",
    )
    assert value["source_ref"]["message_id"] == "m7"  # guardrail 2
    p = eligibility.eligibility_payload(None, "u1", c.session, "en")
    assert status(p["results"]) == {"income_8": "not_applicable", "income_1": "not_met"}
    with pytest.raises(checks.AnswerError, match="one of"):
        answer("professional_course", "maybe", "m8")
    with pytest.raises(checks.AnswerError, match="no such question"):
        answer("nope", "yes", "m9")


def test_answer_tool_in_eligibility_returns_the_eligibility_card(scheme: FakeStore) -> None:
    c = ctx(scheme, "en")
    c.message_id, c.user_text = "m5", "yes it is a professional course"
    args = {"question_id": "professional_course", "answer": "yes", "user_words": c.user_text}
    res = run_tool(c, "answer_requirement", args)
    assert res.ok and res.card.kind == "eligibility"
    assert status(res.card.payload["results"]) == {"income_8": "met", "income_1": "not_applicable"}
