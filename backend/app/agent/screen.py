"""Guided form filling (FORM_FILL.md), in two steps (seen live: one 8B vision call that both read
the page and wrote the guidance took ~28 s a turn and answered Marathi in English):
- READER: a vision model reads the page (fields, options, filled or not, buttons): Groq first,
  the GPU second (settings.screen_reader_primary; a new page read on the T4 took 10-13 s). It runs
  only for a new page or on Help, in the background; the reading is cached per connection.
- WRITER: a text model (Groq first, the GPU second) writes what Aster says from the reading, the
  user's checked values and the recent talk. No image and no box contents go to it.
The guardrails are applied in code to the writer's output (postprocess). The LLM never gets a tool
loop here. Frames live in this process's memory only (guardrail 7): never written to disk, the
database or the logs."""

import asyncio
import base64
import json
import logging
import re
import time
import uuid
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from typing import Any, Literal, get_args

from pydantic import BaseModel, field_validator

from app.agent.prompts import read, t
from app.agent.tools import Ctx
from app.config import Settings
from app.db import supabase as repo
from app.llm.client import LLMUnavailable, Provider, chat_stream
from app.speech.stream import Speaker
from app.verify.checks import readiness
from app.verify.contradictions import same
from app.verify.names import in_devanagari
from app.verify.validator import DEV_DIGITS, KIND, numbers, parse_date
from app.ws.protocol import AgentState, AssistantMessage, Guidance, GuideField, PauseGuidance

log = logging.getLogger(__name__)

Row = dict[str, Any]
LANG_NAMES = {"mr": "Marathi", "hi": "Hindi", "en": "English"}
FRAMES_KEPT = 3
FRESH_S = 10.0  # a frame this recent belongs to the user's question
READ_FIELDS = 8
CHECK_FIELDS = 20


class Frames:
    """The last few frames of one connection, in memory (LRU of 3)."""

    def __init__(self, keep: int = FRAMES_KEPT) -> None:
        self.keep = keep
        self._d: OrderedDict[str, tuple[float, str, bytes]] = OrderedDict()

    def put(self, frame_id: str, data: bytes, reason: str) -> None:
        self._d[frame_id] = (time.monotonic(), reason, data)
        self._d.move_to_end(frame_id)
        while len(self._d) > self.keep:
            self._d.popitem(last=False)

    def take_utterance(self, max_age: float = FRESH_S) -> tuple[str, bytes] | None:
        """The frame sent with the user's last utterance, once. Only that one: in Private mode or
        while paused the client sends none, and an older frame must not be looked at again."""
        for fid, (at, reason, data) in reversed(self._d.items()):
            if reason == "utterance":
                del self._d[fid]
                return (fid, data) if time.monotonic() - at <= max_age else None
        return None

    def __len__(self) -> int:
        return len(self._d)


PageKind = Literal[
    "login", "otp", "captcha", "form", "review", "submit_confirm", "payment", "other"
]
FieldType = Literal["text", "dropdown", "radio", "checkbox", "date", "file", "other"]
AnswerSource = Literal["checked_value", "student_said", "not_known"]


def _cut(v: Any, n: int) -> Any:
    return v[:n] if isinstance(v, (str, list)) else v


class SeenField(BaseModel):
    """One box as the reader saw it. Never what it contains (that may be a typed Aadhaar number)."""

    label: str
    type: FieldType = "text"
    options: list[str] = []  # the visible choices of a radio group or an open dropdown
    appears_filled: bool = False

    @field_validator("label", mode="before")
    @classmethod
    def _label(cls, v: Any) -> Any:
        return _cut(v, 150)

    @field_validator("options", mode="before")
    @classmethod
    def _options(cls, v: Any) -> Any:
        return [_cut(o, 100) for o in _cut(v, 12)] if isinstance(v, list) else v


_TYPES = set(get_args(FieldType))


def _compact(f: Any) -> Any:
    """ "label|type|filled|choice/choice" -> a SeenField dict. The reader writes fields this way:
    JSON keys on every field doubled its output (247 vs 140 tokens, ~5 s on the T4)."""
    if not isinstance(f, str):
        return f
    parts = f.split("|")
    at = max((i for i, p in enumerate(parts) if i and p.strip().lower() in _TYPES), default=None)
    if at is None:
        return {"label": f.strip()}
    rest = [p.strip() for p in parts[at + 1 :]]
    return {
        "label": "|".join(parts[:at]).strip(),
        "type": parts[at].strip().lower(),
        "appears_filled": bool(rest) and rest[0].lower() in ("1", "true", "yes"),
        "options": [o.strip() for o in rest[1].split("/") if o.strip()] if len(rest) > 1 else [],
    }


class Reading(BaseModel):
    """What the reader saw. Whether the page is sensitive is decided in code (classify)."""

    page_kind: PageKind = "other"
    page_title: str = ""
    fields: list[SeenField] = []
    buttons: list[str] = []

    @field_validator("page_title", mode="before")
    @classmethod
    def _title(cls, v: Any) -> Any:
        return _cut(v, 200)

    @field_validator("fields", mode="before")
    @classmethod
    def _fields(cls, v: Any) -> Any:
        return [_compact(f) for f in _cut(v, READ_FIELDS)] if isinstance(v, list) else v

    @field_validator("buttons", mode="before")
    @classmethod
    def _buttons(cls, v: Any) -> Any:
        return [_cut(b, 100) for b in _cut(v, 20)] if isinstance(v, list) else v


class Written(BaseModel):
    """What the writer wants to say, before the guardrails."""

    field_label: str = ""  # the box it is about ("" = none, e.g. press a button)
    field_key: str = ""  # a key from the checked values, or ""
    answer_source: AnswerSource = "not_known"
    value: str = ""  # the checked value it suggests, as listed
    instruction: str = ""


# The model picks the box; the value shown comes from the checked fields, never from its words.
# Like the chat (profile.MASKED), it doesn't need to see a phone number to do that.
HIDDEN_FROM_MODEL = {"mobile": "(on file)"}


def _model_fields(fields: list[Row]) -> list[Row]:
    """Identifiers are left out: the model never sees even their last 4 digits."""
    return [
        {
            "field_key": f["field_key"],
            "label": f["label"],
            "value": HIDDEN_FROM_MODEL.get(f["field_key"]) or _portal(f),
            **({"in_english_letters": f["in_english"]} if f.get("in_english") else {}),
        }
        for f in fields
        if f["field_key"] not in IDENTIFIER_KEYS
    ]


def _portal(f: Row) -> str:
    """The value as Indian portals want it: dates DD/MM/YYYY (the model copies what it is given;
    seen live: "Type 2005-05-12" in a DD/MM/YYYY box)."""
    value = str(f["value"])
    if KIND.get(f["field_key"]) == "date" and (d := parse_date(value)):
        return d.strftime("%d/%m/%Y")
    return value


async def _json_call(
    s: Settings,
    ctx: Ctx,
    msgs: list[Row],
    kind: str,
    fmt: Row,
    max_tokens: int,
    prefer: Provider | None = None,
) -> tuple[str, Provider | None]:
    """-> (the reply text, the provider that served it)."""
    text, served = "", None
    async for ch in chat_stream(
        s,
        msgs,
        sensitive_kind=kind,  # a fallback call is audited first (llm/client.py)
        user_id=ctx.user_id,
        session_id=ctx.session["id"],
        prefer=prefer,
        temperature=0,
        max_tokens=max_tokens,
        response_format=fmt,
        reasoning_effort="none",  # Groq Qwen: no thinking tokens (Ollama /v1 ignores it)
    ):
        served = ch.provider
        text += ch.delta.get("content") or ""
    return text, served


# ---------- READER: vision, the page only ----------
def reader_schema() -> Row:
    """Decode time dominates on the T4 (~21 tok/s): a free JSON reading took ~20 s (pretty-printed,
    every box on the page). The schema keeps it on one line, capped, fields as compact strings."""
    props: Row = {
        "page_kind": {"type": "string", "enum": list(get_args(PageKind))},
        "page_title": {"type": "string"},
        "fields": {"type": "array", "maxItems": READ_FIELDS, "items": {"type": "string"}},
        "buttons": {"type": "array", "maxItems": 12, "items": {"type": "string"}},
    }
    schema = {"type": "object", "properties": props, "required": [*props]}
    return {"type": "json_schema", "json_schema": {"name": "screen", "schema": schema}}


async def read_screen(s: Settings, ctx: Ctx, frame: bytes) -> Reading | None:
    """-> the reader's view of one frame, or None (no LLM, or no valid JSON twice)."""
    image = "data:image/jpeg;base64," + base64.b64encode(frame).decode()
    msgs: list[Row] = [
        {
            "role": "system",
            "content": read("screen_reader").replace("{max_fields}", str(READ_FIELDS)),
        },
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Read this screen."},
                {"type": "image_url", "image_url": {"url": image}},
            ],
        },
    ]
    fmt = reader_schema()
    for attempt in range(2):
        try:
            raw, _ = await _json_call(
                s, ctx, msgs, "screen_frame", fmt, 700, prefer=s.screen_reader_primary
            )
        except LLMUnavailable as e:
            log.warning("screen read: no LLM (%s)", str(e)[:200])  # provider + status only
            if fmt["type"] == "json_object":
                return None
            fmt = {"type": "json_object"}  # a fallback model without json_schema support
            continue
        try:
            return Reading.model_validate(json.loads(raw))
        except ValueError as e:
            # The type only: the text may describe what is on the user's screen.
            log.warning("screen read invalid (attempt %d): %s", attempt + 1, type(e).__name__)
            msgs += [
                {"role": "assistant", "content": raw[:2000]},
                {"role": "user", "content": f"Not valid: {str(e)[:300]}. Return the JSON only."},
            ]
    return None


class Reader:
    """The last reading of one connection's screen, in memory. A new page starts a read in the
    background at once; a question about an unchanged page reuses it (no vision call)."""

    def __init__(self, read_fn: Callable[[bytes], Awaitable[Reading | None]]) -> None:
        self._read_fn = read_fn
        self.frame_id: str | None = None
        self.reading: Reading | None = None
        self.frame: bytes | None = None  # the page that reading is of (a check looks at it again)
        self.fields: list[Row] | None = None  # the checked values, loaded with a read
        self._task: asyncio.Task | None = None
        self._next: tuple[str, bytes] | None = None

    @property
    def busy(self) -> bool:
        return self._task is not None and not self._task.done()

    @property
    def has(self) -> bool:
        return self.reading is not None

    def refresh(self, frame_id: str, frame: bytes) -> None:
        if self.busy:
            self._next = (frame_id, frame)  # the page moved on meanwhile: read it next
            return
        self._task = asyncio.create_task(self._run(frame_id, frame))

    async def _run(self, frame_id: str, frame: bytes) -> None:
        while True:
            try:
                self.reading = await self._read_fn(frame)
            except Exception:
                log.exception("screen read crashed")
                self.reading = None
            self.frame_id, self.frame = frame_id, frame
            if self._next is None:
                return
            (frame_id, frame), self._next = self._next, None

    async def current(self) -> tuple[str | None, Reading | None]:
        """The latest reading, once any read under way is done. A cancelled caller leaves the read
        running (shield): the next question uses it."""
        if self._task:
            await asyncio.shield(self._task)
        return self.frame_id, self.reading

    def close(self) -> None:
        if self._task:
            self._task.cancel()
        self.frame = None


# ---------- CHECK: what is typed on the page vs the checked values ----------
# "verify if other fields are correct", "सब सही है?", "बरोबर आहे का?"
# ponytail: keywords, so "what's the correct option?" also runs a check; let the writer decide
# if that bites.
VERIFY = re.compile(
    r"verif|\bcheck|correct|\bright\b|wrong|mistake|सही|ठीक|बरोबर|चूक|गलत|तपास|जाँच|जांच|चेक",
    re.I,
)


_LONG_DIGITS = re.compile(r"\d[\d\s-]{3,}\d")  # a label never holds a number like this; a value may


async def check_screen(s: Settings, ctx: Ctx, frame: bytes, fields: list[Row]) -> list[str] | None:
    """-> "label|field_key|typed" per filled box, or None. The model gets the field keys and labels
    only, never the checked values: it must copy what is typed, not what we expect."""
    keys = [{"field_key": f["field_key"], "label": f["label"]} for f in _model_fields(fields)]
    image = "data:image/jpeg;base64," + base64.b64encode(frame).decode()
    prompt = read("screen_checker").replace("{max_fields}", str(CHECK_FIELDS))
    msgs: list[Row] = [
        {"role": "system", "content": prompt.replace("{fields}", json.dumps(keys))},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Read the filled boxes."},
                {"type": "image_url", "image_url": {"url": image}},
            ],
        },
    ]
    for _ in range(2):
        try:
            raw, _ = await _json_call(
                s, ctx, msgs, "screen_frame", {"type": "json_object"}, 900,
                prefer=s.screen_reader_primary,
            )  # fmt: skip
            boxes = json.loads(raw).get("boxes")
            if isinstance(boxes, list):
                return [str(b) for b in boxes[:CHECK_FIELDS]]
        except LLMUnavailable as e:
            log.warning("screen check: no LLM (%s)", str(e)[:200])
            return None
        except (ValueError, AttributeError) as e:  # the type only: it describes the screen
            log.warning("screen check invalid: %s", type(e).__name__)
    return None


def verdict(boxes: list[str], fields: list[Row], lang: str) -> str:
    """The boxes the checker read -> what matches, what does not, what the student checks
    themselves. Compared in code (same()), never by a model. What is typed is never repeated (it
    may be an identifier the model failed to blank); only labels and the checked values are."""
    by_key = {f["field_key"]: f for f in fields if f["field_key"] not in IDENTIFIER_KEYS}

    def by_value(v: str) -> Row | None:  # same script only: same() calls Marathi vs English equal
        dev = bool(_DEVANAGARI.search(v))
        return next(
            (
                f
                for k, f in by_key.items()
                if bool(_DEVANAGARI.search(_portal(f))) == dev and same(k, v, _portal(f))
            ),
            None,
        )

    ok, bad, unknown, own = [], [], [], []
    unplaced = 0
    for b in boxes:
        parts = b.rsplit("|", 2)
        label, key, typed = parts if len(parts) == 3 else (b, "", "")
        label, key, typed = label.strip(" *"), key.strip(), typed.strip().translate(DEV_DIGITS)
        if any(rx.search(label) for rx, _ in _SECRET_FIELDS):
            continue
        if _identifier(key, label):
            own.append(label)
            continue
        # A box whose name was scrolled off comes back with its value as the label (seen live:
        # "I have no checked value for Kasliwal Harsh Padam"). Such a label is never shown.
        if (
            label in ("", "?")
            or _norm(label) == _norm(typed)
            or _LONG_DIGITS.search(label)
            or (not typed and by_value(label))
        ):
            label, typed = "", typed or label
        f = by_key.get(key) or (None if label else by_value(typed))
        if f is None:
            if label:
                unknown.append(label)
            else:
                unplaced += 1  # said, but what is typed in it is not repeated
            continue
        name = label or f["label"]
        expected = (
            _on_aadhaar(f, label)
            if _AS_ON_AADHAAR.search(label)
            else _portal({**f, "value": _english(str(f["value"]), f, label)})
        )
        if expected is None or (f["field_key"] == "full_name" and _NAME_PART.search(label)):
            own.append(name)  # no Aadhaar read, or one part of a name: theirs to check
            continue
        if typed and same(f["field_key"], typed, expected):
            ok.append(name)
        else:
            bad.append((name, _portal(f)))
    if not (ok or bad or unknown or own or unplaced):
        return t(lang, "fill.check.none") or ""
    out = [(t(lang, "fill.check.bad") or "").format(label=lb, value=v) for lb, v in bad]
    if ok:
        out.append((t(lang, "fill.check.ok") or "").format(labels=", ".join(ok)))
    if unknown:
        out.append((t(lang, "fill.check.unknown") or "").format(labels=", ".join(unknown)))
    if own:
        out.append((t(lang, "fill.check.self") or "").format(labels=", ".join(own)))
    if unplaced:
        out.append((t(lang, "fill.check.unplaced") or "").format(n=unplaced))
    return " ".join(out)


# ---------- WRITER: text only ----------
_DEVANAGARI = re.compile(r"[ऀ-ॿ]")


def wrong_language(text: str, lang: str) -> bool:
    """A Marathi/Hindi reply must be in Devanagari (seen live: asked for Marathi, the 8B model
    answered in English)."""
    return lang in ("mr", "hi") and not _DEVANAGARI.search(text)


async def write(
    s: Settings,
    ctx: Ctx,
    r: Reading,
    fields: list[Row],
    question: str | None,
    history: str,
) -> tuple[Written | None, Provider | None]:
    """-> what to say about the page (Groq first, the GPU second), or None."""
    system = (
        read("screen_writer")
        .replace("{page}", json.dumps(r.model_dump(), ensure_ascii=False))
        .replace("{fields}", json.dumps(_model_fields(fields), ensure_ascii=False))
        .replace("{history}", history or "(nothing yet)")
        .replace("{lang_name}", LANG_NAMES.get(ctx.lang, "English"))
    )
    # Guardrail 6: a spoken Aadhaar/account number never leaves for Groq (stored rows already are)
    note = (
        f"The student just said: {repo.redact_ids(question)}"
        if question
        else "What should the student do now?"
    )
    msgs: list[Row] = [{"role": "system", "content": system}, {"role": "user", "content": note}]
    fmt = {"type": "json_object"}
    for attempt in range(2):
        try:
            raw, served = await _json_call(
                s, ctx, msgs, "screen_text", fmt, max_tokens=300, prefer="fallback"
            )
        except LLMUnavailable as e:
            log.warning("screen write: no LLM (%s)", str(e)[:200])
            return None, None
        try:
            w = Written.model_validate(json.loads(raw))
            if wrong_language(w.instruction, ctx.lang):
                raise ValueError(f"instruction must be in {LANG_NAMES[ctx.lang]}, in Devanagari")
            return w, served
        except ValueError as e:
            log.warning("screen write invalid (attempt %d): %s", attempt + 1, type(e).__name__)
            msgs += [
                {"role": "assistant", "content": raw[:2000]},
                {"role": "user", "content": f"Not valid: {str(e)[:300]}. Return the JSON only."},
            ]
    return None, None


# ---------- post-processing: the guardrails live here, in code, not in the prompt ----------
# Guardrail 5: nothing is suggested on these pages; guidance pauses until the page changes. A
# review page is where the final Submit is (seen live: the mock submit page came back "review").
PAUSE_KINDS = {"login", "otp", "captcha", "payment", "submit_confirm", "review"}
# A secret field anywhere on the page makes it sensitive, whatever the model called the page.
_SECRET_FIELDS = (
    (re.compile(r"pass\s*word|पासवर्ड", re.I), "login"),
    (re.compile(r"\botp\b|one[\s-]*time|ओटीपी", re.I), "otp"),
    (re.compile(r"captcha|कॅप्चा|कैप्चा", re.I), "captcha"),
    # a PIN, not a "Pin Code" (seen live: "Current Institute Pin Code" paused a form as payment)
    (re.compile(r"\bcvv\b|\bpin\b(?!\s*-?\s*code)|card\s*number|\bupi\b", re.I), "payment"),
)
# Guardrail 6: typed by the user from the document, never suggested (we only hold the last 4).
IDENTIFIER_KEYS = {"aadhaar_last4": "aadhaar", "bank_account_last4": "bank_passbook"}
_IDENTIFIER_LABELS = (
    # "Aadhaar No.", "आधार क्रमांक", a bare "Aadhaar"; not "Full Name (as per Aadhaar)" (seen live)
    (
        re.compile(
            r"(aadh?aa?r|आधार)\s*(card\s*)?(no\b|num|#|क्र|नं|सं)|^\W*(aadh?aa?r|आधार)\W*$|\buid\b",
            re.I,
        ),
        "aadhaar",
    ),
    (
        re.compile(r"(account|a/c|ac)\.?\s*(no|num)|खाते\s*क्र|खाता\s*(सं|नं|क्र)", re.I),
        "bank_passbook",
    ),
)
# The final, irreversible submit (guardrail 5: Aster never submits, and pauses here).
_FINAL_SUBMIT = re.compile(
    r"final\s*submit|submit\s*(the\s*)?application|अंतिम|confirm\s*submi", re.I
)
DOC_NAMES = {"aadhaar": "Aadhaar card", "bank_passbook": "bank passbook"}
# "Full name (as per Aadhaar)", "आधारनुसार नाव": only the Aadhaar's own text goes in such a box
# (seen live: the Class 10 marksheet's "KASLIWAL HARSH" suggested for "First name as on Aadhaar").
_AS_ON_AADHAAR = re.compile(
    r"\b(per|on|in)\s+(the\s+|your\s+)?aadh?aa?r|aadh?aa?r\s*(प्रमाणे|नुसार)"
    r"|आधार\s*(कार्ड\s*)?(प्रमाणे|नुसार|के\s*अनुसार|अनुसार|पर)",
    re.I,
)


def _on_aadhaar(f: Row, label: str = "") -> str | None:
    """The field's value as read off the Aadhaar (portal format), or None if none was read. An
    English box gets the same name in English letters when the Aadhaar was read in Devanagari."""
    if f.get("on_aadhaar"):
        return _portal({**f, "value": _english(f["on_aadhaar"], f, label)})
    return (
        _portal({**f, "value": _english(str(f["value"]), f, label)})
        if _source(f) == DOC_NAMES["aadhaar"]
        else None
    )


def _english(value: str, f: Row, label: str) -> str:
    """A Devanagari name -> its checked English twin (checks._in_english) for a box labelled in
    English letters; anything else unchanged."""
    twin = f.get("in_english")
    if twin and in_devanagari(value) and not in_devanagari(label):
        return str(twin)
    return value


# A box for one part of a name: a full name is never typed into it whole.
_NAME_PART = re.compile(
    r"\b(first|middle|last|given|sur)\s*-?\s*name|surname|पहिले नाव|मधले नाव|आडनाव|पहला नाम|उपनाम",
    re.I,
)
_DIGITS = re.compile(r"\d[\d,]*(?:\.\d+)?")
_CHOICE_TYPES = {"dropdown", "radio"}


def _values(f: Row) -> list[str]:
    return [str(v) for v in (f["value"], f.get("in_english")) if v]


def _source(f: Row) -> str:
    return str(f.get("source") or "").split(" · ")[0]


def _identifier(key: str | None, label: str) -> str | None:
    """-> the document an identifier is typed from, or None."""
    if key in IDENTIFIER_KEYS:
        return IDENTIFIER_KEYS[key]
    return next((doc for rx, doc in _IDENTIFIER_LABELS if rx.search(label)), None)


def recent_talk(messages: list[Row], keep: int = 10) -> str:
    """The last few things said, for answers the portal asks but no document holds (seen live:
    "No, it is not a renewal application" was said, then the model was asked about renewal with
    no memory of it). Text only, each line cut short."""
    lines = [
        f"{'Student' if m['role'] == 'user' else 'Aster'}: {' '.join(m['content'].split())[:200]}"
        for m in messages
        if m["role"] in ("user", "assistant") and m.get("content")
    ]
    return "\n".join(lines[-keep:])


def invented_number(text: str, fields: list[Row]) -> bool:
    """Free text with a number (3+ digits) that is none of the user's checked values, e.g. an OTP
    the model made up ("use 123456", seen live) or anything read off the screen."""
    allowed = [n for f in fields for n in numbers(str(f["value"]))]
    for m in _DIGITS.findall(text):
        if len(re.sub(r"\D", "", m)) < 3:
            continue
        if not any(abs(n - a) < 0.01 for n in numbers(m) for a in allowed):
            return True
    return False


_QUOTED = re.compile(r"(?<!\w)['‘\"“]([^'‘’\"“”]{1,60})['’\"”](?!\w)")
_PRESS = re.compile(r"click|press|tap|button|बटन|बटण|क्लिक|दबा|दाबा", re.I)


def _norm(x: str) -> str:
    return re.sub(r"\W+", "", x).casefold()


def unseen_quote(text: str, r: Reading, target: GuideField | None) -> bool:
    """Free text that tells them to press a quoted thing the reading does not have: no such
    button, or an answer with no checked value. Seen live: "Click the 'Next' button" with no Next
    on screen, "Click 'Yes' for 'Is admitted under EWS seat?'" with no value for it."""
    seen = [*r.buttons, *(f.label for f in r.fields)]
    seen += [x for x in (target.option_text, target.value) if x] if target else []
    known = [_norm(x) for x in seen]
    # Only orders to press something: "If your parent is a farmer, choose 'Yes'" explains a
    # question and stays.
    pressed = [x for x in re.split(r"(?<=[.!?।])\s+", text) if _PRESS.search(x)]
    quoted = [_norm(q) for x in pressed for q in _QUOTED.findall(x)]
    return any(q and not any(q in k for k in known) for q in quoted)


def _say(g: GuideField, lang: str) -> str:
    if g.identifier:
        return g.note or ""
    if g.option_text:
        return (t(lang, "fill.choose") or "").format(label=g.label, option=g.option_text)
    return (t(lang, "fill.type") or "").format(label=g.label, value=g.value)


def _identifier_note(label: str, doc: str, lang: str) -> str:
    name = DOC_NAMES[doc] if lang == "en" else t(lang, "fill.doc_default")
    return (t(lang, "fill.identifier") or "").format(label=label, document=name)


def _seen(f: SeenField, lang: str) -> GuideField:
    if doc := _identifier(None, f.label):
        note = _identifier_note(f.label, doc, lang)
        return GuideField(label=f.label, filled=f.appears_filled, identifier=True, note=note)
    return GuideField(label=f.label, filled=f.appears_filled)


def skip_told(r: Reading, said: list[Row], lang: str) -> Reading:
    """The reading the writer gets: an Aadhaar/account box Aster already told them to type
    themselves counts as handled, so guidance moves on (seen live: "Aadhaar Number: please type…"
    said after every other box, and again after "I will do it later")."""
    told = {m["content"] for m in said if m["role"] == "assistant"}
    fields = [
        f.model_copy(update={"appears_filled": True})
        if (doc := _identifier(None, f.label)) and _identifier_note(f.label, doc, lang) in told
        else f
        for f in r.fields
    ]
    return r.model_copy(update={"fields": fields})


def classify(r: Reading) -> tuple[str, bool]:
    """-> (page kind, sensitive), decided in code whatever the reader called the page."""
    kind: str = r.page_kind
    if any(_FINAL_SUBMIT.search(b) for b in r.buttons):
        kind = "submit_confirm"
    elif (
        kind == "review"
        and not any(re.search(r"submit|सबमिट", b, re.I) for b in r.buttons)
        and any(not f.appears_filled and f.type != "other" for f in r.fields)
    ):
        kind = "form"  # empty boxes and no submit: a misread form
    secret = next((k for f in r.fields for rx, k in _SECRET_FIELDS if rx.search(f.label)), None)
    if kind not in PAUSE_KINDS and secret:
        kind = secret
    return kind, kind in PAUSE_KINDS


def postprocess(
    r: Reading | None,
    w: Written | None,
    fields: list[Row],
    lang: str,
    frame_id: str,
    question: str | None = None,
) -> Guidance:
    """The reading + the writer's words -> what the user sees and hears. Only checked values are
    suggested; identifiers never; nothing at all on login/OTP/captcha/payment/submit pages."""
    base: Row = {"frame_id": frame_id, "lang": lang}
    if r is None:
        text = t(lang, "fill.unreadable") or ""
        return Guidance(**base, page_kind="other", sensitive=False, page_title="", instruction=text)
    kind, sensitive = classify(r)
    if sensitive:
        key = "submit_confirm" if kind == "review" else kind
        labels = [GuideField(label=f.label, filled=f.appears_filled) for f in r.fields]
        return Guidance(
            **base,
            page_kind=kind,
            sensitive=True,
            page_title=r.page_title,
            instruction=t(lang, f"fill.pause.{key}") or "",
            fields=labels,
        )
    out = [_seen(f, lang) for f in r.fields]
    page: Row = {**base, "page_kind": kind, "sensitive": False, "page_title": r.page_title}
    if w is None:
        return Guidance(**page, instruction=t(lang, "fill.no_writer") or "", fields=out)
    allowed = _model_fields(fields)  # what the writer was given: identifiers are not in it
    by_key = {f["field_key"]: f for f in fields if f["field_key"] not in IDENTIFIER_KEYS}

    # The box it is about: the reader's box with that label, else just the label.
    norm = _norm(w.field_label)
    i = next((i for i, g in enumerate(out) if norm and _norm(g.label) == norm), None)
    if i is None:
        i = next((i for i, g in enumerate(out) if norm and norm in _norm(g.label)), None)
    target = out[i] if i is not None else None
    if target is None and (w.field_label or w.field_key):
        target = GuideField(label=w.field_label or w.field_key)
    said = w.instruction.strip()
    f = by_key.get(w.field_key)
    if target and (doc := _identifier(w.field_key, target.label)):
        target.identifier, target.note = True, _identifier_note(target.label, doc, lang)
        said = ""  # the template only: never the writer's words near an Aadhaar/account box
    elif target and f:
        value: str | None = _portal({**f, "value": _english(str(f["value"]), f, target.label)})
        source = _source(f)
        if w.value and not any(same(f["field_key"], v, w.value) for v in _values(f)):
            said = ""  # guardrail 2: it named a value that is not the checked one
        if _AS_ON_AADHAAR.search(target.label):
            value, source, said = _on_aadhaar(f, target.label), DOC_NAMES["aadhaar"], ""
        if value and value == f.get("in_english") and value != f["value"]:
            # the English letters come from another document: say which (guardrail 2)
            source = f"{f.get('in_english_source') or ''}, same name as your {source}".strip(", ")
        target.field_key, target.source = f["field_key"], source
        if value is None:  # no Aadhaar read: no other document stands in for it (guardrail 2)
            target.note = (t(lang, "fill.as_on_aadhaar") or "").format(label=target.label)
        elif f["field_key"] == "full_name" and _NAME_PART.search(target.label):
            # Which part is the first name is the user's call: documents differ in order.
            target.note = (t(lang, "fill.name_part") or "").format(label=target.label, value=value)
            said = ""
        else:
            option = None
            if i is not None and r.fields[i].type in _CHOICE_TYPES:
                opts = r.fields[i].options
                option = next((o for o in opts if same(f["field_key"], value, o)), value)
            target.value, target.option_text = value, option
    elif w.answer_source == "checked_value":
        said = ""  # it claims a checked value it was not given
    if said and (invented_number(said, allowed) or unseen_quote(said, r, target)):
        said = ""

    if target and (target.identifier or (target.note and not target.value)):
        instruction = target.note or ""
    elif target and target.value and not (question and said):
        instruction = _say(target, lang)  # the template: the checked value, in their language
    elif said:
        instruction = said
    elif any(not g.filled for g in out):
        instruction = t(lang, "fill.no_writer") or ""
    else:
        instruction = t(lang, "fill.page_done") or ""
    return Guidance(**page, instruction=instruction, target=target, fields=out)


async def run_screen_turn(
    s: Settings,
    ctx: Ctx,
    send: Any,
    reader: Reader,
    question: str | None = None,
    speak: Callable[[str], Speaker] | None = None,
    announce: bool = False,
    talk: Awaitable[list[Row]] | None = None,
) -> Guidance:
    """The latest reading (+ the user's words) -> guidance on screen, spoken. A new instruction is
    also stored as Aster's message (text only). announce: the user asked (Help, Done, or spoke),
    so the reply is said even if it repeats, and "Let me look at your screen…" fills the silence
    while a vision read is under way (only then). talk: the recent messages, if the caller already
    started loading them (during speech-to-text)."""
    looking = reader.busy
    await send(AgentState(state="thinking", detail="Looking at your screen" if looking else None))
    t0 = time.monotonic()
    speakers: list[Speaker] = []
    try:
        if speak and announce and looking:
            speakers.append(speak(str(uuid.uuid4())))
            speakers[0].feed(t(ctx.lang, "fill.looking") or "")
            speakers[0].flush()

        async def checked() -> list[Row]:
            if reader.fields is None or looking:  # values do not change while filling
                ready = await asyncio.to_thread(readiness, ctx.db, ctx.user_id, ctx.session)
                reader.fields = ready["fields"]
            return reader.fields

        sid = ctx.session["id"]
        talk = talk or asyncio.to_thread(repo.list_messages, ctx.db, ctx.user_id, sid, 16)
        fields, said, (frame_id, r) = await asyncio.gather(checked(), talk, reader.current())
        read_ms = round((time.monotonic() - t0) * 1000)
        w, writer = None, None
        check = (
            bool(question and VERIFY.search(question))
            and r is not None
            and not classify(r)[1]
            and reader.frame is not None
        )
        if check:
            await send(AgentState(state="thinking", detail="Checking what you typed"))
            boxes = await check_screen(s, ctx, reader.frame, fields)  # type: ignore[arg-type]
            g = postprocess(r, None, fields, ctx.lang, frame_id or "")
            text = verdict(boxes, fields, ctx.lang) if boxes is not None else None
            g = g.model_copy(update={"instruction": text or t(ctx.lang, "fill.unreadable") or ""})
        else:
            if r is not None and not classify(r)[1]:
                told = skip_told(r, said, ctx.lang)
                w, writer = await write(s, ctx, told, fields, question, recent_talk(said))
            g = postprocess(r, w, fields, ctx.lang, frame_id or "", question)
        guided_ms = round((time.monotonic() - t0) * 1000)
        await send(g)
        if g.sensitive:
            await send(PauseGuidance(reason=g.page_kind))
        for sp in speakers:
            await sp.finish()
        # A repeat is skipped only for automatic frames: when the user asked, silence reads as
        # broken (seen live: five questions in a row went unanswered on a done page).
        if g.instruction and (announce or g.instruction != ctx.last_guidance):
            ctx.last_guidance = g.instruction
            mid = str(uuid.uuid4())
            row = {"id": mid, "role": "assistant", "content": g.instruction, "lang": ctx.lang}
            row["provider"] = "screen"
            await asyncio.to_thread(repo.add_message, ctx.db, ctx.user_id, sid, row)
            await send(AssistantMessage(message_id=mid, text=g.instruction, lang=ctx.lang))  # type: ignore[arg-type]
            if speak:
                speakers.append(speak(mid))
                await send(AgentState(state="speaking"))
                speakers[-1].feed(g.instruction)
                await speakers[-1].finish()
        heard = speakers[-1].first_audio_at if speakers else None
        log.info(  # timings and the page kind only (guardrail 7)
            "screen_turn vision=%s read_ms=%s guided_ms=%s first_audio_ms=%s writer=%s page=%s",
            looking,
            read_ms,
            guided_ms,
            round((heard - t0) * 1000) if heard else None,
            writer,
            g.page_kind,
        )
    except asyncio.CancelledError:  # the user spoke over it, or went private
        for sp in speakers:
            sp.cancel()
        raise
    await send(AgentState(state="idle"))
    return g
