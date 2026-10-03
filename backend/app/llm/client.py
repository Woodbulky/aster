"""LLM provider routing + OpenAI-compatible streaming client.

GPU gateway first (URL discovered from Supabase `gpu_endpoints`, cached 30 s), hosted fallback
second. Each provider has a circuit breaker. A provider that fails before its first token is
skipped for the next one; once tokens flow, an error propagates (no duplicate text)."""

import asyncio
import json
import logging
import re
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

import httpx

from app.config import Settings
from app.db import supabase as repo

log = logging.getLogger(__name__)

Provider = Literal["gpu", "fallback"]

DISCOVERY_TTL_S = 30.0
FIRST_TOKEN_TIMEOUT_S = 8.0  # ARCHITECTURE: LLM chat/tools
VISION_FIRST_TOKEN_TIMEOUT_S = 20.0  # ARCHITECTURE: vision
# Ollama sends a tool call only once it is complete: a save_research with a few quotes took 11.8 s
# on the T4 before its first chunk, and the 8 s limit threw that answer away (seen live). A dead
# tunnel still fails fast on connect, so this only waits for a slow-but-working GPU.
TOOLS_FIRST_TOKEN_TIMEOUT_S = 30.0
_B64 = re.compile(r"[A-Za-z0-9+/=_-]{80,}")
# A 429 means "wait", not "down": waiting beats an apology (seen live: a research turn is 6-7
# rounds and Groq's free tier allows 8k tokens/min). Longer waits than this fail as before.
RATE_LIMIT_MAX_WAIT_S = 30.0
RATE_LIMIT_RETRIES = 2
_TRY_AGAIN = re.compile(r"try again in ([0-9.]+)s")


class RateLimited(httpx.HTTPStatusError):
    def __init__(self, msg: str, *, request: httpx.Request, response: httpx.Response, wait: float):
        super().__init__(msg, request=request, response=response)
        self.wait = wait


STREAM_TIMEOUT = httpx.Timeout(30.0, connect=5.0)  # per-read gap once streaming


@dataclass(frozen=True)
class Route:
    provider: Provider
    # Sensitive input (document image, screen frame) going to the hosted fallback: an
    # audit_events(action="llm.sensitive_fallback", payload={"provider": "fallback", "kind"}) row
    # is written. The image/frame itself never goes in the payload (guardrail 7).
    audit: bool


@dataclass
class Breaker:
    """3 consecutive failures -> skip for 60 s. After the cooldown one call is let through; if it
    fails, the breaker opens again straight away."""

    threshold: int = 3
    cooldown: float = 60.0
    clock: Callable[[], float] = time.monotonic
    fails: int = 0
    opened_at: float | None = field(default=None)

    def ok(self) -> bool:
        return self.opened_at is None or self.clock() - self.opened_at >= self.cooldown

    def success(self) -> None:
        self.fails, self.opened_at = 0, None

    def failure(self) -> None:
        self.fails += 1
        if self.fails >= self.threshold:
            self.opened_at = self.clock()


breakers: dict[Provider, Breaker] = {"gpu": Breaker(), "fallback": Breaker()}
_discovery: tuple[float, str | None] | None = None  # (fetched_at monotonic, url)
_http: httpx.AsyncClient | None = None
_http_loop: asyncio.AbstractEventLoop | None = None


# ---------- GPU discovery ----------
def _fetch_gpu_row(s: Settings) -> dict[str, Any] | None:
    if not (s.supabase_url and s.supabase_secret_key):
        return None
    q = repo.get_db().table("gpu_endpoints").select("url,last_seen").eq("name", s.gpu_worker_name)
    rows = q.limit(1).execute().data
    return rows[0] if rows else None


def _fresh(last_seen: str | None, stale_s: int) -> bool:
    if not last_seen:
        return False
    age = datetime.now(UTC) - datetime.fromisoformat(last_seen)
    return age.total_seconds() < stale_s


def _discover(s: Settings) -> str | None:
    global _discovery
    now = time.monotonic()
    if _discovery and now - _discovery[0] < DISCOVERY_TTL_S:
        return _discovery[1]
    try:
        row = _fetch_gpu_row(s)
    except Exception as e:  # discovery must never take the app down
        log.warning("gpu discovery failed: %s", e)
        row = None
    url = (
        row["url"].rstrip("/")
        if row and _fresh(row.get("last_seen"), s.gpu_stale_seconds)
        else None
    )
    _discovery = (now, url)
    return url


def reset_discovery() -> None:
    global _discovery
    _discovery = None


def gpu_url(s: Settings) -> str | None:
    """Gateway URL, or None. LLM_PRIMARY=fallback skips discovery entirely (saves Kaggle hours)."""
    if s.llm_primary == "fallback":
        return None
    return s.gpu_url_override.rstrip("/") or _discover(s)


def fallback_ready(s: Settings) -> bool:
    return bool(s.fallback_llm_base_url and s.fallback_llm_api_key and s.fallback_llm_model)


def providers(s: Settings) -> list[Provider]:
    """Usable providers in order, skipping open breakers."""
    out: list[Provider] = []
    if gpu_url(s) and breakers["gpu"].ok():
        out.append("gpu")
    if fallback_ready(s) and breakers["fallback"].ok():
        out.append("fallback")
    return out


def route(s: Settings, *, sensitive: bool = False) -> Route | None:
    """Provider to use now. None = no LLM available."""
    p = providers(s)
    if not p:
        return None
    return Route(p[0], audit=sensitive and p[0] == "fallback")


# ---------- streaming ----------
@dataclass(frozen=True)
class Chunk:
    provider: Provider
    delta: dict[str, Any]  # raw OpenAI `choices[0].delta`: content and/or tool_calls
    finish_reason: str | None = None


class LLMUnavailable(RuntimeError):
    pass


def _client() -> httpx.AsyncClient:
    # A client is tied to the event loop that made it: once that loop closes, make a new one
    # (seen in the live test: "Event loop is closed" after a request's own loop ended).
    global _http, _http_loop
    if _http is None or (_http_loop is not None and _http_loop.is_closed()):
        _http = httpx.AsyncClient(timeout=STREAM_TIMEOUT)
        try:
            _http_loop = asyncio.get_running_loop()
        except RuntimeError:  # built outside a loop (e.g. a sync chain builder): keep it
            _http_loop = None
    return _http


def _target(s: Settings, p: Provider) -> tuple[str, str, list[str]]:
    """(chat completions URL, model, api keys to try in order)."""
    if p == "gpu":
        return f"{gpu_url(s)}/v1/chat/completions", s.brain_model, [s.gateway_token]
    keys = [k.strip() for k in s.fallback_llm_api_key.split(",") if k.strip()]
    base = s.fallback_llm_base_url.rstrip("/")
    return f"{base}/chat/completions", s.fallback_llm_model, keys


async def _sse(s: Settings, p: Provider, body: dict[str, Any]) -> AsyncIterator[Chunk]:
    url, model, keys = _target(s, p)
    # ponytail: always starts at key 1, so a rate-limited first key costs one extra round trip.
    # Groq limits are per organization: rotation only helps if the keys are from different orgs.
    for i, key in enumerate(keys):
        req = _client().build_request(
            "POST", url, json={**body, "model": model}, headers={"Authorization": f"Bearer {key}"}
        )
        resp = await _client().send(req, stream=True)
        try:
            if resp.status_code == 429 and i < len(keys) - 1:
                continue
            if resp.status_code == 429:
                text = (await resp.aread()).decode(errors="replace")
                m = _TRY_AGAIN.search(text)
                header = resp.headers.get("retry-after", "")
                wait = float(m.group(1)) if m else float(header) if header.isdigit() else 10.0
                raise RateLimited(f"{p} 429", request=req, response=resp, wait=wait)
            if resp.status_code >= 400:
                # Redact base64 runs: an error body may echo an image/frame (guardrail 7).
                body_text = (await resp.aread()).decode(errors="replace")
                detail = _B64.sub("[redacted]", body_text)[:300]
                raise httpx.HTTPStatusError(
                    f"{p} {resp.status_code}: {detail}", request=req, response=resp
                )
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    return
                for ch in json.loads(data).get("choices") or []:
                    yield Chunk(p, ch.get("delta") or {}, ch.get("finish_reason"))
            return
        finally:
            await resp.aclose()


def _has_image(messages: list[dict[str, Any]]) -> bool:
    return any(
        isinstance(m.get("content"), list)
        and any(part.get("type") == "image_url" for part in m["content"])
        for m in messages
    )


async def chat_stream(
    s: Settings,
    messages: list[dict[str, Any]],
    *,
    tools: list[dict[str, Any]] | None = None,
    sensitive_kind: str | None = None,
    user_id: str | None = None,
    session_id: str | None = None,
    **params: Any,
) -> AsyncIterator[Chunk]:
    """Stream an OpenAI-compatible chat completion. Images go in as `image_url` parts with a
    base64 data URI (Ollama does not fetch remote URLs). `sensitive_kind` (e.g. "document_image",
    "screen_frame") marks the input as sensitive; it is required for any call with images."""
    if _has_image(messages) and not sensitive_kind:
        raise ValueError("image input needs sensitive_kind")
    if sensitive_kind and not user_id:
        raise ValueError("sensitive calls need user_id for the audit trail")

    body: dict[str, Any] = {"messages": messages, "stream": True, **params}
    if tools:
        body["tools"] = tools
    if sensitive_kind:
        first_token_s = VISION_FIRST_TOKEN_TIMEOUT_S
    elif tools:
        first_token_s = TOOLS_FIRST_TOKEN_TIMEOUT_S
    else:
        first_token_s = FIRST_TOKEN_TIMEOUT_S

    for attempt in range(RATE_LIMIT_RETRIES + 1):
        waits: list[float] = []
        async for chunk in _first_provider(
            s, body, first_token_s, sensitive_kind, user_id, session_id, waits
        ):
            yield chunk
        if not waits:
            return  # served (or failed for real: _first_provider raised)
        wait = min(waits)
        if attempt == RATE_LIMIT_RETRIES or wait > RATE_LIMIT_MAX_WAIT_S:
            raise LLMUnavailable(f"rate limited (retry in {wait:.0f}s)")
        log.info("llm rate limited, waiting %.1fs", wait)
        await asyncio.sleep(wait + 0.5)


async def _first_provider(
    s: Settings,
    body: dict[str, Any],
    first_token_s: float,
    sensitive_kind: str | None,
    user_id: str | None,
    session_id: str | None,
    waits: list[float],
) -> AsyncIterator[Chunk]:
    """Stream from the first provider that answers. Rate-limited providers add their wait to
    `waits` and return without raising, so the caller can wait and retry; other failures count
    on the breaker and raise LLMUnavailable once every provider failed."""
    errors: list[str] = []
    for p in await asyncio.to_thread(providers, s):
        if sensitive_kind and p == "fallback":
            # Fail closed: no audit row, no sensitive call.
            payload = {"provider": "fallback", "kind": sensitive_kind}
            await asyncio.to_thread(
                repo.write_audit,
                repo.get_db(),
                user_id,
                session_id,
                "llm.sensitive_fallback",
                payload,
            )
        stream = _sse(s, p, body)
        try:
            first = await asyncio.wait_for(anext(stream), first_token_s)
        except RateLimited as e:
            await stream.aclose()
            waits.append(e.wait)  # busy, not broken: the breaker is not touched
            continue
        except (TimeoutError, StopAsyncIteration, httpx.HTTPError, ValueError) as e:
            await stream.aclose()
            breakers[p].failure()
            if p == "gpu":
                reset_discovery()  # the tunnel URL may have changed
            errors.append(f"{p}: {type(e).__name__} {e}")
            log.warning("llm %s failed before first token: %s", p, e)
            continue
        breakers[p].success()
        yield first
        async for chunk in stream:
            yield chunk
        waits.clear()
        return
    if not waits:
        raise LLMUnavailable("; ".join(errors) or "no LLM provider configured")
