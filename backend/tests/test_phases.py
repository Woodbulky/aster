import pytest

from app.agent.phases import CORE_FIELDS, TOOLS_BY_PHASE, missing_core, next_phase
from tests.conftest import COMPLETE_PROFILE

PARTIAL = {k: v for k, v in COMPLETE_PROFILE.items() if k != "category"}


@pytest.mark.parametrize(
    "phase,portal,profile,expected",
    [
        ("onboarding", None, None, "onboarding"),
        ("onboarding", None, PARTIAL, "onboarding"),
        ("onboarding", "mahadbt", PARTIAL, "onboarding"),  # form chosen early: profile first
        ("onboarding", None, COMPLETE_PROFILE, "choose_form"),
        ("onboarding", "mahadbt", COMPLETE_PROFILE, "research"),  # skips choose_form
        ("choose_form", None, COMPLETE_PROFILE, "choose_form"),
        ("choose_form", "mahadbt", COMPLETE_PROFILE, "research"),
        ("choose_form", None, PARTIAL, "choose_form"),  # never moves back on its own
        ("research", "mahadbt", PARTIAL, "research"),  # later phases own their exits
        ("documents", "mahadbt", None, "documents"),
    ],
)
def test_next_phase(phase, portal, profile, expected) -> None:
    assert next_phase({"phase": phase, "portal": portal}, profile) == expected


def test_blank_counts_as_missing() -> None:
    assert missing_core({**COMPLETE_PROFILE, "district": ""}) == ["district"]
    assert missing_core(None) == list(CORE_FIELDS)


def test_phase_tools() -> None:
    # Profile writes only in onboarding; the form can only be set in choose_form.
    assert "propose_profile_update" not in TOOLS_BY_PHASE["choose_form"]
    assert "set_form" not in TOOLS_BY_PHASE["onboarding"]
