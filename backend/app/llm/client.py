"""LLM provider routing. The OpenAI-compatible client, discovery cache and breaker arrive in M2."""

from dataclasses import dataclass
from typing import Literal

from app.config import Settings

Provider = Literal["gpu", "fallback"]


@dataclass(frozen=True)
class Route:
    provider: Provider
    # Sensitive input (document image, screen frame) going to the hosted fallback: the caller must
    # write audit_events(action="llm.sensitive_fallback", payload={"provider": "fallback", "kind"}).
    # Never put the image/frame itself in the payload (guardrail 7).
    audit: bool


def gpu_url(s: Settings) -> str | None:
    """Gateway URL, or None. LLM_PRIMARY=fallback skips discovery entirely (saves Kaggle hours)."""
    if s.llm_primary == "fallback":
        return None
    # TODO(M2): Supabase gpu_endpoints discovery (fresh last_seen, 30 s cache) + breaker state.
    return s.gpu_url_override or None


def fallback_ready(s: Settings) -> bool:
    return bool(s.fallback_llm_base_url and s.fallback_llm_api_key)


def route(s: Settings, *, sensitive: bool = False) -> Route | None:
    """Provider to use now. GPU first (unless LLM_PRIMARY=fallback); sensitive inputs may still
    use the fallback, but only with an audit flag. None = no LLM available."""
    if gpu_url(s):
        return Route("gpu", audit=False)
    if fallback_ready(s):
        return Route("fallback", audit=sensitive)
    return None
