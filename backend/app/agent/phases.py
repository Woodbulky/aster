"""Deterministic phase machine. Transitions come from DB state, never from the LLM (AGENT.md)."""

from typing import Any, Literal

Phase = Literal[
    "onboarding",
    "choose_form",
    "research",
    "eligibility",
    "documents",
    "verification",
    "ready",
    "form_fill",
    "done",
]

# PRODUCT.md "Onboarding": ~10 core details. Trim here to shorten the demo.
CORE_FIELDS: tuple[str, ...] = (
    "full_name",
    "dob",
    "gender",
    "district",
    "category",
    "annual_family_income",
    "ssc_year",
    "ssc_percentage",
    "hsc_year",
    "hsc_percentage",
    "current_course",
    "current_year",
)

TOOLS_BY_PHASE: dict[str, tuple[str, ...]] = {
    "onboarding": ("get_profile", "propose_profile_update", "explain_why_asked"),
    "choose_form": ("get_profile", "list_supported_forms", "suggest_schemes", "set_form"),
}


def missing_core(profile: dict[str, Any] | None) -> list[str]:
    p = profile or {}
    return [k for k in CORE_FIELDS if p.get(k) in (None, "")]


def next_phase(session: dict[str, Any], profile: dict[str, Any] | None) -> Phase:
    """Phase the session should be in now. Only moves forward out of the M3 phases; later phases
    own their own exits (M5+)."""
    phase: Phase = session["phase"]
    if phase not in ("onboarding", "choose_form"):
        return phase
    if missing_core(profile):
        return phase  # never back from choose_form to onboarding on its own
    return "research" if session.get("portal") else "choose_form"
