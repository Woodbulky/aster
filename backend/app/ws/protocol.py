"""WS messages (docs/API.md). Mirrored in web/src/lib/ws/protocol.ts — change both together.
Voice/screen messages arrive with M4/M7."""

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
    name: Literal["profile_confirmed", "profile_rejected", "form_selected"]
    payload: dict[str, Any] = {}


class Ping(_In):
    type: Literal["ping"]


ClientMsg = TypeAdapter(Annotated[Hello | UserText | UiEvent | Ping, Field(discriminator="type")])


class FormSelected(_In):
    """ui_event form_selected payload (tap on a scheme_suggestions card)."""

    portal: Annotated[str, StringConstraints(max_length=50)]
    scheme_key: Annotated[str, StringConstraints(max_length=100)] | None = None


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
