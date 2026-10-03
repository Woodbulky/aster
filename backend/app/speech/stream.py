"""Sentence-streamed TTS for one assistant message: every finished sentence is synthesised
concurrently and sent in `seq` order as soon as it is ready (docs/VOICE.md)."""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable

from app.config import Settings
from app.speech.router import synthesize
from app.speech.sentences import SentenceSplitter, normalize_for_tts

log = logging.getLogger(__name__)

# (seq, text, audio+mime or None when TTS failed) -> sent to the client by the caller
MAX_SENTENCES = 15  # backstop to REPLY_MAX_TOKENS: never synthesize a runaway reply

Emit = Callable[[int, str, tuple[bytes, str] | None], Awaitable[None]]


class Speaker:
    def __init__(self, s: Settings, lang: str, emit: Emit) -> None:
        self.s, self.lang, self.emit = s, lang, emit
        self.split = SentenceSplitter()
        self.queue: asyncio.Queue[tuple[int, str, asyncio.Task | None]] = asyncio.Queue()
        self.tasks: list[asyncio.Task] = []
        self.seq = 0
        self.first_audio_at: float | None = None
        self.pump = asyncio.create_task(self._pump())

    def feed(self, delta: str) -> None:
        for sentence in self.split.feed(delta):
            self._enqueue(sentence)

    def _enqueue(self, text: str) -> None:
        spoken = normalize_for_tts(text).strip()
        if not spoken or self.seq >= MAX_SENTENCES:
            return
        task = asyncio.create_task(synthesize(self.s, spoken, self.lang))
        self.tasks.append(task)
        # the normalised text: a tts_unavailable fallback must not read a full ID aloud either
        self.queue.put_nowait((self.seq, spoken, task))
        self.seq += 1

    async def _pump(self) -> None:
        while True:
            seq, text, task = await self.queue.get()
            if task is None:  # sentinel: no more sentences
                return
            try:
                audio = await task
            except asyncio.CancelledError:
                raise
            except Exception as e:  # SpeechUnavailable or a provider error: client speaks it
                log.warning("tts seq %d unavailable: %s", seq, type(e).__name__)
                audio = None
            if audio and self.first_audio_at is None:
                self.first_audio_at = time.monotonic()
            await self.emit(seq, text, audio)

    def flush(self) -> None:
        """Speak what is buffered now, e.g. a short "Thanks!" before a tool round, instead of
        holding it until the next LLM round finishes its first sentence."""
        for sentence in self.split.flush():
            self._enqueue(sentence)

    async def finish(self) -> None:
        """Speak the rest of the reply and wait until everything has been sent."""
        self.flush()
        self.queue.put_nowait((-1, "", None))
        await self.pump

    def cancel(self) -> None:
        self.pump.cancel()
        for t in self.tasks:
            t.cancel()
