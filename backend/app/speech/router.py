"""STT chain sarvam -> local_gpu; TTS chain sarvam. Each try has a timeout and a breaker."""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from app.config import Settings
from app.llm.client import Breaker
from app.speech.base import SpeechUnavailable, STTProvider, Transcript, TTSProvider
from app.speech.local_gpu import LocalGpuSTT
from app.speech.sarvam import SarvamSTT, SarvamTTS

log = logging.getLogger(__name__)
breakers: dict[str, Breaker] = {}  # "stt:sarvam", "tts:sarvam", ...
_http: httpx.AsyncClient | None = None
_http_loop: asyncio.AbstractEventLoop | None = None


def _client() -> httpx.AsyncClient:
    # A client is tied to the event loop that made it: once that loop closes, make a new one
    # (seen in the live test: "Event loop is closed" after a request's own loop ended).
    global _http, _http_loop
    if _http is None or (_http_loop is not None and _http_loop.is_closed()):
        _http = httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=5.0))
        try:
            _http_loop = asyncio.get_running_loop()
        except RuntimeError:  # built outside a loop (e.g. a sync chain builder): keep it
            _http_loop = None
    return _http


def stt_chain(s: Settings) -> list[STTProvider]:
    chain: list[STTProvider] = []
    if s.sarvam_api_key:
        chain.append(SarvamSTT(s, _client()))
    chain.append(LocalGpuSTT(s, _client()))
    return chain


def tts_chain(s: Settings) -> list[TTSProvider]:
    return [SarvamTTS(s, _client())] if s.sarvam_api_key else []


async def _first(kind: str, chain: list[Any], timeout: float, call: Callable[[Any], Awaitable]):
    for p in chain:
        b = breakers.setdefault(f"{kind}:{p.name}", Breaker())
        if not b.ok():
            continue
        t0 = time.monotonic()
        try:
            out = await asyncio.wait_for(call(p), timeout)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # any failure moves on to the next provider
            b.failure()
            log.warning(
                "%s %s failed in %.2fs: %s", kind, p.name, time.monotonic() - t0, type(e).__name__
            )
            continue
        b.success()
        log.info("%s %s ok in %.2fs", kind, p.name, time.monotonic() - t0)
        return out
    raise SpeechUnavailable(kind)


async def transcribe(
    s: Settings,
    audio: bytes,
    mime: str,
    lang_hint: str | None,
    chain: list[STTProvider] | None = None,
) -> Transcript:
    chain = stt_chain(s) if chain is None else chain
    return await _first(
        "stt", chain, s.stt_timeout_s, lambda p: p.transcribe(audio, mime, lang_hint)
    )


async def synthesize(
    s: Settings, text: str, lang: str, chain: list[TTSProvider] | None = None
) -> tuple[bytes, str]:
    chain = tts_chain(s) if chain is None else chain
    return await _first("tts", chain, s.tts_timeout_s, lambda p: p.synthesize(text, lang))
