import { api } from "@/lib/api";
import { ACCEPT, MAX_BYTES } from "@/lib/general-docs";
import { createClient } from "@/lib/supabase/client";
import type { DocStatus } from "@/lib/ws/protocol";

const BUCKET = "documents";
const EXT: Record<string, string> = { "application/pdf": "pdf", "image/jpeg": "jpg", "image/png": "png", "image/webp": "webp" };
const POLL_MS = 2000;
const POLL_LIMIT_MS = 3 * 60_000;

/** Upload to <uid>/<session>/<document_id>.<ext> (storage RLS: own folder only), then register it;
 * the backend reads it in the background. The file name is not kept: it can hold personal details. */
export async function uploadSessionDoc(sessionId: string, docType: string, file: File, quality?: Record<string, number>): Promise<string> {
  if (!ACCEPT.split(",").includes(file.type)) throw new Error("Use a PDF, JPG, PNG or WEBP file.");
  if (file.size > MAX_BYTES) throw new Error("Files must be 10 MB or smaller.");
  const sb = createClient();
  const { data } = await sb.auth.getUser();
  if (!data.user) throw new Error("You're signed out. Please sign in again.");
  const id = crypto.randomUUID();
  const { error } = await sb.storage.from(BUCKET).upload(`${data.user.id}/${sessionId}/${id}.${EXT[file.type]}`, file, { contentType: file.type });
  if (error) throw new Error("Upload failed. Please try again.");
  await api("POST", `/api/sessions/${sessionId}/documents`, { document_id: id, doc_type: docType, mime: file.type, quality });
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

/** Latest document per type for a session, so a reloaded checklist shows the real state. */
export async function sessionDocStatus(sessionId: string): Promise<Record<string, { id: string; status: DocStatus }>> {
  const { data } = await createClient().from("documents").select("id, doc_type, status").eq("session_id", sessionId).order("created_at");
  const out: Record<string, { id: string; status: DocStatus }> = {};
  for (const d of data ?? []) if (d.doc_type) out[d.doc_type] = { id: d.id, status: d.status as DocStatus };
  return out;
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
