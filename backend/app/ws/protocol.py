"""WS messages (docs/API.md). Mirrored in web/src/lib/ws/protocol.ts — change both together."""

import uuid
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, TypeAdapter

Lang = Literal["mr", "hi", "en"]
AgentStateName = Literal["idle", "listening", "thinking", "speaking", "happy", "concerned"]


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------- client -> server ----------
class Hello(_In):
    type: Literal["hello"]
    token: Annotated[str, StringConstraints(max_length=4096)]
    lang: Lang


class UserText(_In):
    type: Literal["user_text"]
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


class UiEvent(_In):
    type: Literal["ui_event"]
    name: Literal[
        "profile_confirmed",
        "profile_rejected",
        "form_selected",
        "documents_requested",
        "document_processed",
        "flag_resolved",
        "screen_share_started",
    ]
    payload: dict[str, Any] = {}


class Ping(_In):
    type: Literal["ping"]


class AudioStart(_In):
    """Followed by ONE binary frame (the utterance) and then audio_end."""

    type: Literal["audio_start"]
    mime: Annotated[str, StringConstraints(max_length=60)]
    lang_hint: Lang | None = None


class AudioEnd(_In):
    type: Literal["audio_end"]


class Interrupt(_In):
    type: Literal["interrupt"]


class ScreenFrame(_In):
    """Followed by ONE binary frame (JPEG). Held in memory only, never written (guardrail 7)."""

    type: Literal["screen_frame"]
    frame_id: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    reason: Literal["utterance", "change", "manual"]


ClientMsg = TypeAdapter(
    Annotated[
        Hello | UserText | UiEvent | Ping | AudioStart | AudioEnd | Interrupt | ScreenFrame,
        Field(discriminator="type"),
    ]
)


class DocumentProcessed(_In):
    """ui_event document_processed payload: the client saw the document finish (status poll)."""

    document_id: uuid.UUID


class FlagResolved(_In):
    """ui_event flag_resolved payload: the user answered a flag card (REST resolve/acknowledge)."""

    flag_id: uuid.UUID


class FormSelected(_In):
    """ui_event form_selected payload (tap on a scheme_suggestions card)."""

    portal: Annotated[str, StringConstraints(max_length=50)] | None = None  # informational
    scheme_key: Annotated[str, StringConstraints(min_length=1, max_length=100)]


# ---------- server -> client ----------
class Ready(BaseModel):
    type: Literal["ready"] = "ready"
    phase: str
    assistant: dict[str, Any]


class AgentState(BaseModel):
    type: Literal["agent_state"] = "agent_state"
    state: AgentStateName
    detail: str | None = None


class AssistantDelta(BaseModel):
    type: Literal["assistant_delta"] = "assistant_delta"
    message_id: str
    text: str


class AssistantMessage(BaseModel):
    type: Literal["assistant_message"] = "assistant_message"
    message_id: str
    text: str
    lang: Lang


class TranscriptMsg(BaseModel):
    type: Literal["transcript"] = "transcript"
    text: str
    lang: Lang
    provider: str


class TtsAudio(BaseModel):
    """The next binary frame is the audio."""

    type: Literal["tts_audio"] = "tts_audio"
    message_id: str
    seq: int
    mime: str


class TtsUnavailable(BaseModel):
    type: Literal["tts_unavailable"] = "tts_unavailable"
    message_id: str
    seq: int
    text: str
    lang: Lang


class TurnMetrics(BaseModel):
    """ms per stage, measured from the end of the user's utterance (dev overlay)."""

    type: Literal["turn_metrics"] = "turn_metrics"
    stt_ms: int | None = None
    llm_first_token_ms: int | None = None
    first_audio_ms: int | None = None
    stt_provider: str | None = None


class ToolEvent(BaseModel):
    type: Literal["tool_event"] = "tool_event"
    name: str
    status: Literal["started", "done", "failed"]
    label: str


class CardMsg(BaseModel):
    type: Literal["card"] = "card"
    card_id: str
    kind: str
    payload: dict[str, Any]


class PhaseMsg(BaseModel):
    type: Literal["phase"] = "phase"
    phase: str


class ErrorMsg(BaseModel):
    type: Literal["error"] = "error"
    code: str
    message: str


class Pong(BaseModel):
    type: Literal["pong"] = "pong"


class GuideField(BaseModel):
    """One visible portal field. value is only ever a checked value of the user's (FORM_FILL.md)."""

    label: str
    field_key: str | None = None
    filled: bool = False
    value: str | None = None  # what to type, in the portal's format
    option_text: str | None = None  # dropdowns: the visible option to choose
    source: str | None = None  # "Income certificate · L3"
    identifier: bool = False  # Aadhaar / account number: typed from the document, never suggested
    note: str | None = None


class Guidance(BaseModel):
    type: Literal["guidance"] = "guidance"
    frame_id: str
    page_kind: str
    sensitive: bool
    page_title: str
    instruction: str
    lang: Lang
    target: GuideField | None = None  # the field to fill now
    fields: list[GuideField] = []


class PauseGuidance(BaseModel):
    """Stop sending frames until the page changes (login/OTP/captcha/payment/submit)."""

    type: Literal["pause_guidance"] = "pause_guidance"
    reason: str
