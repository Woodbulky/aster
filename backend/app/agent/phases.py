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

# Just enough to rank schemes (PRODUCT.md "Onboarding"). Everything else (dob, district, 10th/12th
# results, year of study, admission year, course mode...) is asked when a scheme or form needs it,
# or read from a document: a diploma student is never asked for 12th results to see schemes.
DISCOVERY: tuple[str, ...] = (
    "full_name",
    "current_course",
    "entry_qualification",
    "category",
    "annual_family_income",
)
# What the current course was joined after (profiles.entry_qualification).
ENTRY_PATHS = ("ssc", "hsc", "diploma", "graduation")
HSC_FIELDS = ("hsc_board", "hsc_year", "hsc_percentage")
# Paths with no Class 12 in them: 12th details do not apply (unless the user gave them anyway).
NO_HSC_PATHS = ("ssc", "diploma")

# suggest_schemes + set_form stay available after choose_form so the user can switch schemes;
# the phase then follows the new scheme's research state.
PICK = ("suggest_schemes", "set_form")
# Once documents are attached to this session, another scholarship is a new session instead.
NEW = "new_application"
TOOLS_BY_PHASE: dict[str, tuple[str, ...]] = {
    "onboarding": ("get_profile", "propose_profile_update", "explain_why_asked"),
    "choose_form": ("get_profile", "list_supported_forms", *PICK),
    "research": (
        "get_knowledge_pack",
        "research_scheme",
        "search_web",
        "fetch_url",
        "read_pdf",
        "save_research",
        *PICK,
    ),
    "eligibility": (
        "check_eligibility",
        "answer_requirement",
        "get_profile",
        "propose_profile_update",
        "fetch_url",
        "request_documents",
        *PICK,
    ),
    "documents": (
        "request_documents",
        "answer_requirement",
        "get_document_status",
        "run_verification",
        "list_flags",
        "ask_resolution",
        "resolve_flag",
        "explain_why_asked",
        NEW,
    ),
    "verification": (
        "run_verification",
        "answer_requirement",
        "list_flags",
        "ask_resolution",
        "resolve_flag",
        "readiness_summary",
        "get_document_status",
        "request_documents",
        "explain_why_asked",
        NEW,
    ),
    "ready": (
        "readiness_summary",
        "list_flags",
        "ask_resolution",
        "resolve_flag",
        "get_document_status",
        "run_verification",
        "start_form_fill",
        "mark_submitted",
        NEW,
    ),
    # Screen turns run in code (agent/screen.py); this is only for words without a fresh frame.
    "form_fill": ("readiness_summary", "start_form_fill", "mark_submitted", NEW),
    "done": (NEW,),
}


def missing_core(profile: dict[str, Any] | None) -> list[str]:
    p = profile or {}
    return [k for k in DISCOVERY if p.get(k) in (None, "")]


def not_applicable_fields(profile: dict[str, Any] | None) -> set[str]:
    """Profile fields that do not apply on this education path and are blank (so never asked)."""
    p = profile or {}
    if p.get("entry_qualification") not in NO_HSC_PATHS:
        return set()
    return {k for k in HSC_FIELDS if p.get(k) in (None, "")}


def scheme_of(session: dict[str, Any]) -> str | None:
    """The chosen scheme: a pack key, or the name of a scheme without a pack (live research)."""
    return session.get("scheme_key") or session.get("scheme_name")


def next_phase(
    session: dict[str, Any],
    profile: dict[str, Any] | None,
    has_research: bool = False,
    open_blocks: int = 0,
) -> Phase:
    """Phase the session should be in now. has_research = research is saved for the current
    scheme. research <-> eligibility follows it both ways (switching scheme = research again).
    eligibility -> documents -> verification are the user's call (request_documents,
    run_verification). verification <-> ready follows the open blocking flags."""
    phase: Phase = session["phase"]
    if phase in ("research", "eligibility"):
        return "eligibility" if has_research else "research"
    if phase in ("verification", "ready"):
        return "verification" if open_blocks else "ready"
    if phase not in ("onboarding", "choose_form"):
        return phase
    if missing_core(profile):
        return phase  # never back from choose_form to onboarding on its own
    return "research" if scheme_of(session) else "choose_form"
