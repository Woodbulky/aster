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
export type CriterionCounts = { met: number; not_met: number; unknown: number };
export type SchemeOption = { portal: string; scheme_key: string; name: string; draft: boolean } & CriterionCounts;
export type SchemeSuggestionsPayload = { options: SchemeOption[]; note: string };
export type Source = { url: string; quote: string };
export type CriterionResult = {
  id: string;
  text: string;
  status: "met" | "not_met" | "unknown";
  reason: string; // "Meets this — per <site>" etc. (guardrail 1: never a final verdict)
  source: Source;
  ask_field: string | null;
};
export type EligibilityPayload = {
  scheme_key: string | null;
  name: string;
  origin: "pack" | "live"; // live = researched on the web, unverified
  draft: boolean; // dev only: pack not yet verified by the team
  results: CriterionResult[];
  counts: CriterionCounts;
  deadlines: { label: string; date: string | null; passed: boolean; source: Source }[];
  note: string;
};
export type ResearchItem = { text: string; source_url: string; quote: string; content_id: string; site: string; fetched_on: string };
export type ResearchSummaryPayload = {
  scheme: string;
  eligibility: ResearchItem[];
  documents: ResearchItem[];
  rejected: number; // items dropped because their quote was not on the cited page
  note: string;
};
export type Card =
  | { card_id: string; kind: "confirm_profile"; payload: ConfirmProfilePayload }
  | { card_id: string; kind: "scheme_suggestions"; payload: SchemeSuggestionsPayload }
  | { card_id: string; kind: "eligibility"; payload: EligibilityPayload }
  | { card_id: string; kind: "research_summary"; payload: ResearchSummaryPayload };

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
