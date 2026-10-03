"""Speech provider interfaces (docs/VOICE.md). Log provider + latency + error only, never audio or
transcripts (they carry personal data)."""

from typing import Protocol

from pydantic import BaseModel


class Transcript(BaseModel):
    text: str
    lang: str  # mr | hi | en
    provider: str
    confidence: float | None = None


class SpeechUnavailable(RuntimeError):
    """Every provider in the chain failed or was skipped."""


class STTProvider(Protocol):
    name: str

    async def transcribe(self, audio: bytes, mime: str, lang_hint: str | None) -> Transcript: ...


class TTSProvider(Protocol):
    name: str

    async def synthesize(self, text: str, lang: str) -> tuple[bytes, str]: ...  # (audio, mime)
