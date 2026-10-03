"""Tool registry. Each tool: pydantic args -> ToolResult {ok, data, card?}. The phase decides which
tools exist (phases.TOOLS_BY_PHASE); run_tool enforces it in code, not in the prompt."""

import json
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from supabase import Client

from app.agent.phases import TOOLS_BY_PHASE

log = logging.getLogger(__name__)


@dataclass
class Ctx:
    db: Client
    user_id: str
    session: dict[str, Any]  # form_sessions row, kept current by tools and the orchestrator
    lang: str
    message_id: str | None = None  # latest user message: the evidence for proposals


class Card(BaseModel):
    card_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    kind: str
    payload: dict[str, Any]


class ToolResult(BaseModel):
    ok: bool
    data: Any = None
    error: str | None = None
    card: Card | None = None


class NoArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    label: str  # UI activity label (UI copy is English)
    args: type[BaseModel]
    fn: Callable[[Ctx, Any], ToolResult]


TOOLS: dict[str, Tool] = {}


def register(name: str, description: str, label: str, args: type[BaseModel] = NoArgs):
    def deco(fn: Callable[[Ctx, Any], ToolResult]) -> Callable[[Ctx, Any], ToolResult]:
        TOOLS[name] = Tool(name, description, label, args, fn)
        return fn

    return deco


def schemas(phase: str) -> list[dict[str, Any]]:
    """OpenAI `tools` for the phase."""
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.args.model_json_schema(),
            },
        }
        for t in (TOOLS[n] for n in TOOLS_BY_PHASE.get(phase, ()))
    ]


def _errors(e: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(map(str, err['loc'])) or 'args'}: {err['msg']}" for err in e.errors()
    )[:500]


def run_tool(ctx: Ctx, name: str, raw_args: str | dict[str, Any]) -> ToolResult:
    """Never raises: errors go back to the LLM as {ok: false, error} (AGENT.md failure rules)."""
    phase = ctx.session["phase"]
    if name not in TOOLS_BY_PHASE.get(phase, ()):
        return ToolResult(ok=False, error=f"tool {name!r} is not available in phase {phase}")
    tool = TOOLS[name]
    try:
        raw = json.loads(raw_args or "{}") if isinstance(raw_args, str) else raw_args
        args = tool.args.model_validate(raw)
    except json.JSONDecodeError:
        return ToolResult(ok=False, error="arguments are not valid JSON")
    except ValidationError as e:
        return ToolResult(ok=False, error=_errors(e))
    try:
        return tool.fn(ctx, args)
    except ValidationError as e:
        return ToolResult(ok=False, error=_errors(e))
    except Exception:
        log.exception("tool %s failed", name)
        return ToolResult(ok=False, error="internal error, tell the user plainly")


from app.agent.tools import (  # noqa: E402, F401  (registers)
    documents,
    eligibility,
    forms,
    profile,
    research,
)
