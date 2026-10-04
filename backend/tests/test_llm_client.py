import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.llm import client
from app.main import app

SB = {"supabase_url": "https://sb.example", "supabase_secret_key": "sk"}
FB = {
    "fallback_llm_base_url": "https://fb.example/v1",
    "fallback_llm_api_key": "k1,k2",
    "fallback_llm_model": "fb-model",
}


def s(**kw: Any) -> Settings:
    return Settings(_env_file=None, **kw)


def ago(seconds: float) -> str:
    return (datetime.now(UTC) - timedelta(seconds=seconds)).isoformat()


# ---------- breaker ----------
def test_breaker_opens_after_3_failures_and_retries_after_60s() -> None:
    now = [0.0]
    b = client.Breaker(clock=lambda: now[0])
    b.failure()
    b.failure()
    assert b.ok()
    b.failure()
    assert not b.ok()
    now[0] = 59.9
    assert not b.ok()
    now[0] = 60.0
    assert b.ok()  # half-open: one try
    b.failure()
    assert not b.ok()  # still failing -> open again at once
    now[0] = 200.0
    b.success()
    b.failure()
    assert b.ok()  # success reset the count


def test_open_gpu_breaker_routes_to_fallback() -> None:
    cfg = s(gpu_url_override="https://gpu.example", **FB)
    for _ in range(3):
        client.breakers["gpu"].failure()
    assert client.route(cfg) == client.Route("fallback", audit=False)


# ---------- discovery ----------
def test_discovery_fresh_stale_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    rows: list[dict | None] = [
        {"url": "https://a.trycloudflare.com/", "last_seen": ago(10)},
        {"url": "https://b.trycloudflare.com", "last_seen": ago(181)},
        None,
    ]
    monkeypatch.setattr(client, "_fetch_gpu_row", lambda _s: rows.pop(0))
    cfg = s(**SB)
    assert client.gpu_url(cfg) == "https://a.trycloudflare.com"
    client.reset_discovery()
    assert client.gpu_url(cfg) is None  # last_seen older than GPU_STALE_SECONDS=180
    client.reset_discovery()
    assert client.gpu_url(cfg) is None


def test_gpu_model_comes_from_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    row = {"url": "https://a.trycloudflare.com", "last_seen": ago(10)}
    monkeypatch.setattr(client, "_fetch_gpu_row", lambda _s: dict(row, models={"brain": "m:it"}))
    cfg = s(**SB, brain_model="m")
    assert client._target(cfg, "gpu")[1] == "m:it"
    client.reset_discovery()
    monkeypatch.setattr(client, "_fetch_gpu_row", lambda _s: row)  # older worker: no models
    assert client._target(cfg, "gpu")[1] == "m"


def test_discovery_cached_30s(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    now = [1000.0]
    monkeypatch.setattr(client.time, "monotonic", lambda: now[0])

    def fetch(_s: Settings) -> dict:
        calls.append(1)
        return {"url": f"https://u{len(calls)}.example", "last_seen": ago(1)}

    monkeypatch.setattr(client, "_fetch_gpu_row", fetch)
    cfg = s(**SB)
    assert client.gpu_url(cfg) == "https://u1.example"
    now[0] += 29
    assert client.gpu_url(cfg) == "https://u1.example"
    assert len(calls) == 1
    now[0] += 2
    assert client.gpu_url(cfg) == "https://u2.example"
    assert len(calls) == 2


def test_discovery_error_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(_s: Settings) -> None:
        raise RuntimeError("supabase down")

    monkeypatch.setattr(client, "_fetch_gpu_row", boom)
    assert client.gpu_url(s(**SB)) is None


def test_override_skips_discovery(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(client, "_fetch_gpu_row", lambda _s: pytest.fail("queried"))
    assert client.gpu_url(s(gpu_url_override="https://gpu.example/")) == "https://gpu.example"


# ---------- streaming ----------
def sse(*texts: str) -> bytes:
    lines = [
        "data: " + json.dumps({"choices": [{"delta": {"content": t}, "finish_reason": None}]})
        for t in texts
    ]
    return ("\n\n".join([*lines, "data: [DONE]"]) + "\n\n").encode()


def use_transport(monkeypatch: pytest.MonkeyPatch, handler: Any) -> list[httpx.Request]:
    seen: list[httpx.Request] = []

    async def wrapped(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        out = handler(req)
        return await out if asyncio.iscoroutine(out) else out

    monkeypatch.setattr(client, "_http", httpx.AsyncClient(transport=httpx.MockTransport(wrapped)))
    return seen


def collect(cfg: Settings, messages: list[dict], **kw: Any) -> list[client.Chunk]:
    async def run() -> list[client.Chunk]:
        return [c async for c in client.chat_stream(cfg, messages, **kw)]

    return asyncio.run(run())


HELLO = [{"role": "user", "content": "नमस्कार"}]


def test_streams_from_gpu_with_gateway_token(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = use_transport(monkeypatch, lambda r: httpx.Response(200, content=sse("नम", "स्कार")))
    cfg = s(gpu_url_override="https://gpu.example", gateway_token="gt", **FB)
    chunks = collect(cfg, HELLO)
    assert "".join(c.delta.get("content", "") for c in chunks) == "नमस्कार"
    assert {c.provider for c in chunks} == {"gpu"}
    assert str(seen[0].url) == "https://gpu.example/v1/chat/completions"
    assert seen[0].headers["authorization"] == "Bearer gt"
    assert json.loads(seen[0].content)["model"] == "qwen3-vl:8b-instruct"


def test_gpu_down_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(r: httpx.Request) -> httpx.Response:
        if r.url.host == "gpu.example":
            raise httpx.ConnectError("tunnel gone")
        return httpx.Response(200, content=sse("ok"))

    use_transport(monkeypatch, handler)
    chunks = collect(s(gpu_url_override="https://gpu.example", **FB), HELLO)
    assert [c.provider for c in chunks] == ["fallback"]
    assert client.breakers["gpu"].fails == 1


def test_gpu_slow_first_token_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(client, "FIRST_TOKEN_TIMEOUT_S", 0.2)

    async def handler(r: httpx.Request) -> httpx.Response:
        if r.url.host == "gpu.example":
            await asyncio.sleep(5)
        return httpx.Response(200, content=sse("ok"))

    use_transport(monkeypatch, handler)
    chunks = collect(s(gpu_url_override="https://gpu.example", **FB), HELLO)
    assert [c.provider for c in chunks] == ["fallback"]


def test_tool_calls_get_the_longer_first_token_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ollama sends a tool call only when it is complete (11.8 s for a save_research on the T4,
    seen live): with tools offered, a slow GPU is waited for, not dropped."""
    monkeypatch.setattr(client, "FIRST_TOKEN_TIMEOUT_S", 0.1)
    monkeypatch.setattr(client, "TOOLS_FIRST_TOKEN_TIMEOUT_S", 2.0)

    async def handler(r: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.4)
        return httpx.Response(200, content=sse("ok"))

    use_transport(monkeypatch, handler)
    tools = [{"type": "function", "function": {"name": "t", "parameters": {"type": "object"}}}]
    chunks = collect(s(gpu_url_override="https://gpu.example", **FB), HELLO, tools=tools)
    assert [c.provider for c in chunks] == ["gpu"]


def test_fallback_rotates_key_on_429(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(r: httpx.Request) -> httpx.Response:
        if r.headers["authorization"] == "Bearer k1":
            return httpx.Response(429, content=b"slow down")
        return httpx.Response(200, content=sse("ok"))

    seen = use_transport(monkeypatch, handler)
    chunks = collect(s(**FB), HELLO)
    assert [c.delta["content"] for c in chunks] == ["ok"]
    assert [r.headers["authorization"] for r in seen] == ["Bearer k1", "Bearer k2"]
    assert json.loads(seen[1].content)["model"] == "fb-model"


def test_413_retries_once_with_older_tool_outputs_cut(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(r: httpx.Request) -> httpx.Response:
        if len(r.content) > 3000:
            return httpx.Response(413, content=b"Request too large ... ITPM")
        return httpx.Response(200, content=sse("ok"))

    seen = use_transport(monkeypatch, handler)
    msgs = [
        *HELLO,
        {"role": "tool", "tool_call_id": "a", "content": "x" * 2000},
        {"role": "tool", "tool_call_id": "b", "content": "y" * 900},
    ]
    chunks = collect(s(**FB), msgs)
    assert [c.delta["content"] for c in chunks] == ["ok"]
    assert [r.headers["authorization"] for r in seen] == ["Bearer k1", "Bearer k1"]
    sent = json.loads(seen[1].content)["messages"]
    assert len(sent[1]["content"]) <= client.SHRUNK_TOOL_CHARS + 1  # older one cut
    assert sent[2]["content"] == "y" * 900  # newest kept whole


def test_rate_limit_waits_and_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    """Groq's free tier answers 429 "try again in Xs" mid research turn: wait, retry, and keep
    the breaker closed (it is busy, not down)."""
    slept: list[float] = []

    async def fake_sleep(x: float) -> None:
        slept.append(x)

    monkeypatch.setattr(client.asyncio, "sleep", fake_sleep)
    calls = []

    def handler(r: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) <= 2:  # both keys limited on the first round
            return httpx.Response(429, content=b'{"error":{"message":"Please try again in 4.2s."}}')
        return httpx.Response(200, content=sse("ok"))

    use_transport(monkeypatch, handler)
    chunks = collect(s(**FB), HELLO)
    assert [c.delta["content"] for c in chunks] == ["ok"]
    assert slept == [4.7]
    assert client.breakers["fallback"].fails == 0


def test_rate_limit_too_long_or_repeated_gives_up(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_sleep(_x: float) -> None:
        pass

    monkeypatch.setattr(client.asyncio, "sleep", fake_sleep)
    use_transport(monkeypatch, lambda r: httpx.Response(429, content=b"try again in 90s"))
    with pytest.raises(client.LLMUnavailable, match="rate limited"):
        collect(s(**FB), HELLO)
    use_transport(monkeypatch, lambda r: httpx.Response(429, headers={"retry-after": "2"}))
    with pytest.raises(client.LLMUnavailable, match="rate limited"):
        collect(s(**FB), HELLO)  # 1 try + 2 retries, then the apology
    assert client.breakers["fallback"].fails == 0


def test_all_down_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    use_transport(monkeypatch, lambda r: httpx.Response(500, content=b"err"))
    with pytest.raises(client.LLMUnavailable, match="fallback"):
        collect(s(**FB), HELLO)
    with pytest.raises(client.LLMUnavailable, match="no LLM provider"):
        collect(s(), HELLO)


# ---------- LLM_PRIMARY=fallback ----------
def test_fallback_mode_never_queries_gpu_endpoints(monkeypatch: pytest.MonkeyPatch) -> None:
    def no(*_a: Any) -> None:
        pytest.fail("gpu_endpoints queried in LLM_PRIMARY=fallback")

    monkeypatch.setattr(client, "_fetch_gpu_row", no)
    monkeypatch.setattr(client.repo, "get_db", no)
    cfg = s(llm_primary="fallback", **SB, **FB)

    assert client.gpu_url(cfg) is None
    assert client.route(cfg) == client.Route("fallback", audit=False)
    use_transport(monkeypatch, lambda r: httpx.Response(200, content=sse("ok")))
    assert [c.provider for c in collect(cfg, HELLO)] == ["fallback"]

    from app.config import get_settings

    app.dependency_overrides[get_settings] = lambda: cfg
    try:
        assert TestClient(app).get("/health").json()["providers"]["gpu"] == "off"
    finally:
        app.dependency_overrides.clear()


# ---------- sensitive input ----------
IMAGE = "data:image/jpeg;base64,/9j/SECRETPIXELS"
DOC = [
    {
        "role": "user",
        "content": [
            {"type": "text", "text": "Read this income certificate"},
            {"type": "image_url", "image_url": {"url": IMAGE}},
        ],
    }
]


def capture_audit(monkeypatch: pytest.MonkeyPatch) -> list[tuple]:
    rows: list[tuple] = []
    monkeypatch.setattr(client.repo, "get_db", lambda: "db")
    monkeypatch.setattr(client.repo, "write_audit", lambda *a: rows.append(a))
    return rows


def test_sensitive_fallback_writes_audit_without_image(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = capture_audit(monkeypatch)
    seen = use_transport(monkeypatch, lambda r: httpx.Response(200, content=sse("ok")))
    collect(s(**FB), DOC, sensitive_kind="document_image", user_id="u1", session_id="s1")

    assert rows == [
        (
            "db",
            "u1",
            "s1",
            "llm.sensitive_fallback",
            {"provider": "groq", "kind": "document_image"},
        )
    ]
    assert "SECRETPIXELS" not in repr(rows)
    assert "SECRETPIXELS" in seen[0].content.decode()  # the image did go to the model


def test_sensitive_on_gpu_no_audit(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = capture_audit(monkeypatch)
    use_transport(monkeypatch, lambda r: httpx.Response(200, content=sse("ok")))
    cfg = s(gpu_url_override="https://gpu.example", **FB)
    collect(cfg, DOC, sensitive_kind="document_image", user_id="u1")
    assert rows == []


def test_image_without_sensitive_kind_rejected() -> None:
    with pytest.raises(ValueError, match="sensitive_kind"):
        collect(s(**FB), DOC)
    with pytest.raises(ValueError, match="user_id"):
        collect(s(**FB), DOC, sensitive_kind="document_image")


def test_error_body_with_image_is_redacted(monkeypatch: pytest.MonkeyPatch, caplog) -> None:
    capture_audit(monkeypatch)
    echo = b'{"error": "bad image ' + b"A" * 200 + b'"}'
    use_transport(monkeypatch, lambda r: httpx.Response(400, content=echo))
    with pytest.raises(client.LLMUnavailable) as e:
        collect(s(**FB), DOC, sensitive_kind="document_image", user_id="u1")
    assert "A" * 80 not in str(e.value) and "A" * 80 not in caplog.text
    assert "[redacted]" in str(e.value)
