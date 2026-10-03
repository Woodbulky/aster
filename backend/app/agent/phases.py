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

# suggest_schemes + set_form stay available after choose_form so the user can switch schemes;
# the phase then follows the new scheme's research state.
PICK = ("suggest_schemes", "set_form")
TOOLS_BY_PHASE: dict[str, tuple[str, ...]] = {
    "onboarding": ("get_profile", "propose_profile_update", "explain_why_asked"),
    "choose_form": ("get_profile", "list_supported_forms", *PICK),
    "research": (
        "get_knowledge_pack",
        "search_web",
        "fetch_url",
        "read_pdf",
        "save_research",
        *PICK,
    ),
    "eligibility": (
        "check_eligibility",
        "get_profile",
        "propose_profile_update",
        "fetch_url",
        "request_documents",
        *PICK,
    ),
    "documents": ("request_documents", "get_document_status", "explain_why_asked"),
}


def missing_core(profile: dict[str, Any] | None) -> list[str]:
    p = profile or {}
    return [k for k in CORE_FIELDS if p.get(k) in (None, "")]


def scheme_of(session: dict[str, Any]) -> str | None:
    """The chosen scheme: a pack key, or the name of a scheme without a pack (live research)."""
    return session.get("scheme_key") or session.get("scheme_name")


def next_phase(
    session: dict[str, Any], profile: dict[str, Any] | None, has_research: bool = False
) -> Phase:
    """Phase the session should be in now. has_research = research is saved for the current
    scheme. research <-> eligibility follows it both ways (switching scheme = research again);
    later phases own their own exits (M6+)."""
    phase: Phase = session["phase"]
    if phase in ("research", "eligibility"):
        return "eligibility" if has_research else "research"
    if phase not in ("onboarding", "choose_form"):
        return phase
    if missing_core(profile):
        return phase  # never back from choose_form to onboarding on its own
    return "research" if scheme_of(session) else "choose_form"
