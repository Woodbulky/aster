import pytest

from app.agent.phases import (
    DISCOVERY,
    TOOLS_BY_PHASE,
    missing_core,
    next_phase,
    not_applicable_fields,
)
from tests.conftest import COMPLETE_PROFILE

PARTIAL = {k: v for k, v in COMPLETE_PROFILE.items() if k != "category"}


KEY = {"scheme_key": "demo.obc_aid"}
NAME = {"scheme_name": "Tata Pankh"}


@pytest.mark.parametrize(
    "phase,scheme,profile,researched,expected",
    [
        ("onboarding", {}, None, False, "onboarding"),
        ("onboarding", {}, PARTIAL, False, "onboarding"),
        ("onboarding", KEY, PARTIAL, False, "onboarding"),  # form chosen early: profile first
        ("onboarding", {}, COMPLETE_PROFILE, False, "choose_form"),
        ("onboarding", KEY, COMPLETE_PROFILE, False, "research"),  # skips choose_form
        ("choose_form", {}, COMPLETE_PROFILE, False, "choose_form"),
        ("choose_form", {"portal": "mahadbt"}, COMPLETE_PROFILE, False, "choose_form"),
        ("choose_form", KEY, COMPLETE_PROFILE, False, "research"),
        ("choose_form", NAME, COMPLETE_PROFILE, False, "research"),  # any scholarship
        ("choose_form", {}, PARTIAL, False, "choose_form"),  # never moves back on its own
        ("research", KEY, PARTIAL, False, "research"),
        ("research", NAME, COMPLETE_PROFILE, True, "eligibility"),  # research saved
        ("eligibility", KEY, COMPLETE_PROFILE, True, "eligibility"),
        ("eligibility", NAME, COMPLETE_PROFILE, False, "research"),  # switched scheme
        ("documents", KEY, None, False, "documents"),  # later phases own their exits
    ],
)
def test_next_phase(phase, scheme, profile, researched, expected) -> None:
    assert next_phase({"phase": phase, **scheme}, profile, researched) == expected


def test_blank_counts_as_missing() -> None:
    assert missing_core({**COMPLETE_PROFILE, "current_course": ""}) == ["current_course"]
    assert missing_core(None) == list(DISCOVERY)


def test_discovery_needs_no_12th_or_birth_details() -> None:
    # Applicant: "I did a diploma after Class 10. Why must I enter Class 12 details?"
    diploma = {
        "full_name": "Asha More",
        "current_course": "Diploma in Mechanical Engineering",
        "entry_qualification": "ssc",
        "category": "OBC",
        "annual_family_income": 120000,
    }
    assert missing_core(diploma) == []
    assert next_phase({"phase": "onboarding"}, diploma) == "choose_form"
    # ... but the path itself is asked: without it the 12th question could not be skipped
    assert missing_core({k: v for k, v in diploma.items() if k != "entry_qualification"}) == [
        "entry_qualification"
    ]


def test_12th_does_not_apply_after_10th_or_a_diploma() -> None:
    assert not_applicable_fields({"entry_qualification": "ssc"}) == {
        "hsc_board",
        "hsc_year",
        "hsc_percentage",
    }
    assert not_applicable_fields({"entry_qualification": "diploma", "hsc_year": 2021}) == {
        "hsc_board",
        "hsc_percentage",
    }  # given anyway: used as any other value
    assert not_applicable_fields({"entry_qualification": "hsc"}) == set()
    assert not_applicable_fields({}) == set()


def test_phase_tools() -> None:
    # Profile writes only in onboarding; the form can only be set in choose_form.
    assert "propose_profile_update" not in TOOLS_BY_PHASE["choose_form"]
    assert "set_form" not in TOOLS_BY_PHASE["onboarding"]
    # live research is saved only in research; eligibility can re-read a page but not save
    assert "save_research" in TOOLS_BY_PHASE["research"]
    assert "save_research" not in TOOLS_BY_PHASE["eligibility"]
    assert "check_eligibility" not in TOOLS_BY_PHASE["research"]
    # a question on the eligibility card is answered in that phase
    assert "answer_requirement" in TOOLS_BY_PHASE["eligibility"]
