// Mirror of backend/app/ws/protocol.py (docs/API.md). Change both together.
import type { Lang } from "@/lib/i18n";

export type AgentStateName = "idle" | "listening" | "thinking" | "speaking" | "happy" | "concerned";
export type UiEventName = "profile_confirmed" | "profile_rejected" | "form_selected" | "documents_requested" | "document_processed" | "flag_resolved" | "screen_share_started";

// ---------- client -> server ----------
export type ClientMsg =
  | { type: "hello"; token: string; lang: Lang }
  | { type: "user_text"; text: string }
  | { type: "ui_event"; name: UiEventName; payload: Record<string, unknown> }
  | { type: "ping" }
  | { type: "audio_start"; mime: string; lang_hint: Lang | null } // then ONE binary frame, then audio_end
  | { type: "audio_end" }
  | { type: "interrupt" }
  | { type: "screen_frame"; frame_id: string; reason: FrameReason }; // then ONE binary frame (JPEG), held in backend memory only

export type FrameReason = "utterance" | "change" | "manual";

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
export type DocStatus = "missing" | "uploaded" | "processing" | "extracted" | "failed";
export type ChecklistItem = {
  doc_type: string;
  label: string;
  required: boolean;
  source: Source | null; // null = recommended by Aster, not in the official list
  note: string | null;
  status: DocStatus;
  document_id: string | null;
};
export type DocumentChecklistPayload = { session_id: string; scheme: string; items: ChecklistItem[]; others: string[]; note: string };
export type BBox = [number, number, number, number]; // x0, y0, x1, y1 in page pixels
/** Where a value came from (guardrail 2). Document sources point at OCR lines; bbox null = read by the vision model (no box). */
export type FieldSource = { document_id: string; doc_type: string; line_ids: string[]; page: number; bbox: (BBox | null)[] };
export type PageMeta = { path: string; width: number; height: number };
export type ReviewField = { id: string; field_key: string; label: string; value: string; confidence: number | null; low_confidence: boolean; source: FieldSource };
export type FieldReviewPayload = {
  document_id: string;
  doc_type: string;
  label: string;
  status: DocStatus;
  error: string | null;
  engine: string | null;
  pages: PageMeta[];
  fields: ReviewField[];
  unreadable: string[];
};
export type FlagCandidate = {
  id: string;
  field_key: string;
  value: string;
  source_type: string; // document | profile | voice | text | resolution
  label: string; // "Income certificate · L3", "Your profile"
  document_id: string | null;
  page: PageMeta | null;
  bbox: (BBox | null)[];
  confidence: number | null;
};
/** contradiction | missing_item | low_confidence cards (one FlagCard renders all). Never resolved by Aster: the user picks + gives a reason (guardrail 3). */
export type FlagPayload = {
  flag_id: string;
  session_id: string;
  type: "contradiction" | "rule" | "missing_doc" | "low_confidence";
  severity: "block" | "warn";
  field_key: string | null;
  field_label: string | null;
  message: string;
  candidates: FlagCandidate[];
  can_pick: boolean;
  can_type: boolean;
  doc: { doc_type: string; label: string | null; source: Source | null } | null;
  status: "open" | "resolved" | "acknowledged";
};
export type FlagSummary = { flag_id: string; type: string; severity: "block" | "warn"; field: string | null; message: string | null; values: string[]; status: string };
/** Readiness gate: ready = no open blocking flag. Every value the form will use, with its source. */
export type ReadinessPayload = {
  session_id: string;
  ready: boolean;
  open_block: FlagSummary[];
  open_warn: FlagSummary[];
  acknowledged: (FlagSummary & { reason: string | null })[];
  documents: string[];
  fields: { field_key: string; label: string; value: string; source: string; confirmed: boolean }[];
  note: string;
};
export type StartScreenSharePayload = { session_id: string; scheme: string; portal_url: string | null };
export type Card =
  | { card_id: string; kind: "confirm_profile"; payload: ConfirmProfilePayload }
  | { card_id: string; kind: "scheme_suggestions"; payload: SchemeSuggestionsPayload }
  | { card_id: string; kind: "eligibility"; payload: EligibilityPayload }
  | { card_id: string; kind: "research_summary"; payload: ResearchSummaryPayload }
  | { card_id: string; kind: "document_checklist"; payload: DocumentChecklistPayload }
  | { card_id: string; kind: "field_review"; payload: FieldReviewPayload }
  | { card_id: string; kind: "contradiction"; payload: FlagPayload }
  | { card_id: string; kind: "missing_item"; payload: FlagPayload }
  | { card_id: string; kind: "low_confidence"; payload: FlagPayload }
  | { card_id: string; kind: "readiness"; payload: ReadinessPayload }
  | { card_id: string; kind: "start_screen_share"; payload: StartScreenSharePayload };

/** One visible portal field. `value` is only ever one of the user's checked values (FORM_FILL.md). */
export type GuideField = {
  label: string;
  field_key: string | null;
  filled: boolean;
  value: string | null; // what to type, in the portal's format
  option_text: string | null; // dropdowns: the visible option to choose
  source: string | null; // "Income certificate"
  identifier: boolean; // Aadhaar / account number: typed from the document, never suggested
  note: string | null;
};
export type Guidance = {
  frame_id: string;
  page_kind: string;
  sensitive: boolean;
  page_title: string;
  instruction: string;
  lang: Lang;
  target: GuideField | null; // the field to fill now
  fields: GuideField[];
};

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
  | ({ type: "turn_metrics" } & TurnMetrics)
  | ({ type: "guidance" } & Guidance)
  | { type: "pause_guidance"; reason: string }; // stop sending frames until the page changes

/** ms from the end of the user's utterance (server side). */
export type TurnMetrics = {
  stt_ms: number | null;
  llm_first_token_ms: number | null;
  first_audio_ms: number | null;
  stt_provider: string | null;
};
