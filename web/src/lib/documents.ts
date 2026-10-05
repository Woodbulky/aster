import { api, ensureConsent, NO_CONSENT } from "@/lib/api";
import { ACCEPT, MAX_BYTES } from "@/lib/general-docs";
import { createClient } from "@/lib/supabase/client";
import type { ChecklistItem, DocStatus, EligibilityPayload } from "@/lib/ws/protocol";

const BUCKET = "documents";
const EXT: Record<string, string> = { "application/pdf": "pdf", "image/jpeg": "jpg", "image/png": "png", "image/webp": "webp" };
const POLL_MS = 2000;
const POLL_LIMIT_MS = 3 * 60_000;

/** Upload to <uid>/<session>/<document_id>.<ext> (storage RLS: own folder only), then register it;
 * the backend reads it in the background. The file name is not kept: it can hold personal details. */
export async function uploadSessionDoc(sessionId: string, docType: string, file: File, quality?: Record<string, number>, requirementId?: string): Promise<string> {
  if (!ACCEPT.split(",").includes(file.type)) throw new Error("Use a PDF, JPG, PNG or WEBP file.");
  if (file.size > MAX_BYTES) throw new Error("Files must be 10 MB or smaller.");
  if (!(await ensureConsent("documents"))) throw new Error(NO_CONSENT.documents);
  const sb = createClient();
  const { data } = await sb.auth.getUser();
  if (!data.user) throw new Error("You're signed out. Please sign in again.");
  const id = crypto.randomUUID();
  const { error } = await sb.storage.from(BUCKET).upload(`${data.user.id}/${sessionId}/${id}.${EXT[file.type]}`, file, { contentType: file.type });
  if (error) throw new Error("Upload failed. Please try again.");
  await api("POST", `/api/sessions/${sessionId}/documents`, { document_id: id, doc_type: docType, mime: file.type, quality, requirement_id: requirementId });
  return id;
}

/** Polls the document row (RLS read) until it is read or failed. ponytail: polling; Supabase
 * Realtime on `documents` if many uploads run at once. */
export async function waitForDocument(id: string, onStatus: (s: DocStatus) => void): Promise<DocStatus> {
  const sb = createClient();
  const until = Date.now() + POLL_LIMIT_MS;
  while (Date.now() < until) {
    const { data } = await sb.from("documents").select("status").eq("id", id).maybeSingle();
    const s = (data?.status ?? "uploaded") as DocStatus;
    onStatus(s);
    if (s === "extracted" || s === "failed") return s;
    await new Promise((r) => setTimeout(r, POLL_MS));
  }
  return "failed";
}

export type SessionDoc = { id: string; doc_type: string | null; requirement_id: string | null; status: DocStatus };

/** The session's documents, oldest first, so a reloaded checklist shows the real state. */
export async function sessionDocs(sessionId: string): Promise<SessionDoc[]> {
  const { data } = await createClient().from("documents").select("id, doc_type, requirement_id, status").eq("session_id", sessionId).order("created_at");
  return (data ?? []) as SessionDoc[];
}

/** The latest document that satisfies a requirement (same rule as requirements._matches): one
 * uploaded for it, or a read type it accepts. An "other" only counts for its own requirement. */
export function docFor(item: Pick<ChecklistItem, "id" | "doc_types">, docs: SessionDoc[]): SessionDoc | undefined {
  return [...docs].reverse().find((d) => d.requirement_id === item.id || (d.doc_type !== null && d.doc_type !== "other" && item.doc_types.includes(d.doc_type)));
}

/** A tap answer to a document question. -> the checklist items after it. */
export async function answerRequirement(sessionId: string, questionId: string, answer: string, lang: string): Promise<ChecklistItem[]> {
  const res = await api<{ items: ChecklistItem[] }>("POST", `/api/sessions/${sessionId}/requirements/answer`, { question_id: questionId, answer, lang });
  return res.items;
}

/** A tap answer to a question on the eligibility card. -> the card after it. */
export async function answerEligibility(sessionId: string, questionId: string, answer: string, lang: string): Promise<EligibilityPayload> {
  return api<EligibilityPayload>("POST", `/api/sessions/${sessionId}/eligibility/answer`, { question_id: questionId, answer, lang });
}

export async function pageUrl(path: string): Promise<string | null> {
  const { data } = await createClient().storage.from(BUCKET).createSignedUrl(path, 300);
  return data?.signedUrl ?? null;
}

export type FlagState = { status: "open" | "resolved" | "acknowledged"; resolution: { reason?: string; candidate_id?: string | null; via?: string; value?: string } | null };

export async function flagState(flagId: string): Promise<FlagState | null> {
  const { data } = await createClient().from("flags").select("status, resolution").eq("id", flagId).maybeSingle();
  return (data as FlagState | null) ?? null;
}

/** The user's answer to a flag card: a candidate or a typed value (+ reason) confirms a value;
 * neither acknowledges it. */
export async function answerFlag(sessionId: string, flagId: string, answer: { candidate_id?: string; value?: string; reason: string }): Promise<string> {
  const ack = !answer.candidate_id && !answer.value;
  const path = `/api/sessions/${sessionId}/flags/${flagId}/${ack ? "acknowledge" : "resolve"}`;
  const res = await api<{ status: string }>("POST", path, ack ? { reason: answer.reason } : answer);
  return res.status;
}
