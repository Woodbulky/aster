// Mirror of backend/app/ws/protocol.py (docs/API.md). Change both together.
import type { Lang } from "@/lib/i18n";

export type AgentStateName = "idle" | "listening" | "thinking" | "speaking" | "happy" | "concerned";
export type UiEventName = "profile_confirmed" | "profile_rejected" | "form_selected";

// ---------- client -> server ----------
export type ClientMsg =
  | { type: "hello"; token: string; lang: Lang }
  | { type: "user_text"; text: string }
  | { type: "ui_event"; name: UiEventName; payload: Record<string, unknown> }
  | { type: "ping" }
  | { type: "audio_start"; mime: string; lang_hint: Lang | null } // then ONE binary frame, then audio_end
  | { type: "audio_end" }
  | { type: "interrupt" };

// ---------- cards ----------
export type ConfirmProfilePayload = { proposal_id: string; updates: Record<string, string | number> };
export type SchemeOption = { portal: string; scheme_key: string | null; name: string };
export type SchemeSuggestionsPayload = { options: SchemeOption[]; note: string };
export type Card =
  | { card_id: string; kind: "confirm_profile"; payload: ConfirmProfilePayload }
  | { card_id: string; kind: "scheme_suggestions"; payload: SchemeSuggestionsPayload };

// ---------- server -> client ----------
export type ServerMsg =
  | { type: "ready"; phase: string; assistant: { name: string; avatar_id: string } }
  | { type: "agent_state"; state: AgentStateName; detail: string | null }
  | { type: "assistant_delta"; message_id: string; text: string }
  | { type: "assistant_message"; message_id: string; text: string; lang: Lang }
  | { type: "tool_event"; name: string; status: "started" | "done" | "failed"; label: string }
  | ({ type: "card" } & Card)
  | { type: "phase"; phase: string }
  | { type: "error"; code: string; message: string }
  | { type: "pong" }
  | { type: "transcript"; text: string; lang: Lang; provider: string }
  | { type: "tts_audio"; message_id: string; seq: number; mime: string } // the next binary frame is the audio
  | { type: "tts_unavailable"; message_id: string; seq: number; text: string; lang: Lang }
  | ({ type: "turn_metrics" } & TurnMetrics);

/** ms from the end of the user's utterance (server side). */
export type TurnMetrics = {
  stt_ms: number | null;
  llm_first_token_ms: number | null;
  first_audio_ms: number | null;
  stt_provider: string | null;
};
