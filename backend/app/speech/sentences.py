"""Sentence splitting for streamed TTS + text normalisation (docs/VOICE.md)."""

import re

from app.db.supabase import redact_ids

_END = re.compile(r"[.?!।\n]")
# The first chunk may also end at a comma/colon: Aster starts talking sooner (latency budget).
_FIRST_END = re.compile(r"[.?!।\n,;:]")
MIN_CHARS, MAX_CHARS = 25, 220


class SentenceSplitter:
    """feed() text deltas, get back complete sentences; flush() returns the remainder."""

    def __init__(self) -> None:
        self.buf = ""
        self.first = True

    def feed(self, delta: str) -> list[str]:
        self.buf += delta
        out: list[str] = []
        while (cut := self._cut()) is not None:
            if sentence := self.buf[:cut].strip():
                out.append(sentence)
                self.first = False
            self.buf = self.buf[cut:]
        return out

    def _cut(self) -> int | None:
        for m in (_FIRST_END if self.first else _END).finditer(self.buf):
            # "3.5" / "1,200": a dot or comma before a digit does not end a sentence; at the very
            # end of the buffer more digits may follow, so wait for the next character.
            if m.group() in ".,":
                if m.end() == len(self.buf) or self.buf[m.end()].isdigit():
                    continue
            if m.end() >= MIN_CHARS:
                return m.end()
        if len(self.buf) > MAX_CHARS:
            sp = self.buf.rfind(" ", 0, MAX_CHARS)
            return sp if sp > 0 else MAX_CHARS
        return None

    def flush(self) -> list[str]:
        rest, self.buf = self.buf.strip(), ""
        return [rest] if rest else []


_REDACTED = re.compile(r"\[number ending (\d{4})\]")  # redact_ids() output
_RUPEE = re.compile(r"(?:₹|Rs\.?)\s?([\d,]+(?:\.\d+)?)")
_DATE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_MASK = re.compile(r"(?:[Xx*•]{2,}[\s-]*)+(\d{4})\b")
_EMOJI = re.compile("[🀀-🫿☀-➿️]")  # not U+200D: Marathi ZWJ
_MONTHS = ["", "January", "February", "March", "April", "May", "June", "July", "August",
           "September", "October", "November", "December"]  # fmt: skip


def _date(d: str, m: str, y: str) -> str:
    mi = int(m)
    return f"{int(d)} {_MONTHS[mi]} {y}" if 1 <= mi <= 12 else f"{d}/{m}/{y}"


def normalize_for_tts(text: str) -> str:
    # Guardrails 5/6: a full Aadhaar/bank number is never sent to TTS or read aloud.
    text = _REDACTED.sub(r"ending in \1", redact_ids(text))
    text = _RUPEE.sub(lambda m: f"{m[1].replace(',', '')} rupees", text)
    text = _DATE.sub(lambda m: _date(m[1], m[2], m[3]), text)
    text = _ISO.sub(lambda m: _date(m[3], m[2], m[1]), text)
    text = _MASK.sub(lambda m: f"ending in {m[1]}", text)
    text = _EMOJI.sub("", text)
    return re.sub(r"[*_`#]+", "", text)  # markdown marks are not spoken
