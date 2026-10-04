import type { Database } from "@/lib/database.types";
import { ensureConsent, NO_CONSENT } from "@/lib/api";
import { createClient } from "@/lib/supabase/client";

type DocType = NonNullable<Database["public"]["Tables"]["documents"]["Row"]["doc_type"]>;

/**
 * Documents nearly every form asks for, uploaded once and reused.
 * Aadhaar and bank passbook are left out on purpose: guardrail 6 (full numbers are never stored).
 */
export const GENERAL_DOCS: { type: DocType; label: string; hint: string }[] = [
  { type: "ssc_marksheet", label: "Class 10 marksheet", hint: "SSC / 10th board result" },
  { type: "hsc_marksheet", label: "Class 12 marksheet", hint: "HSC / 12th board result" },
  { type: "domicile_certificate", label: "Domicile certificate", hint: "Proof you live in the state" },
  { type: "income_certificate", label: "Income certificate", hint: "Family income, from the Tehsildar" },
  { type: "caste_certificate", label: "Caste certificate", hint: "If you belong to a reserved category" },
  { type: "caste_validity", label: "Caste validity certificate", hint: "Needed by many MahaDBT schemes" },
];

export const ACCEPT = "application/pdf,image/jpeg,image/png,image/webp";
export const MAX_BYTES = 10 * 1024 * 1024;

export type StoredDoc = { path: string; size: number; uploadedAt: string };

const BUCKET = "documents";
// Storage RLS only allows paths under the caller's own uid folder.
const folder = (uid: string, type: DocType) => `${uid}/general/${type}`;

async function uid(): Promise<string> {
  const { data, error } = await createClient().auth.getUser();
  if (error || !data.user) throw new Error("Not signed in");
  return data.user.id;
}

/** Latest upload per document type. There is no delete/update policy, so a replacement is a new object. */
export async function listGeneralDocs(): Promise<Partial<Record<DocType, StoredDoc>>> {
  const id = await uid();
  const storage = createClient().storage.from(BUCKET);
  const lists = await Promise.all(
    GENERAL_DOCS.map(({ type }) =>
      storage.list(folder(id, type), { sortBy: { column: "created_at", order: "desc" }, limit: 1 }),
    ),
  );
  const out: Partial<Record<DocType, StoredDoc>> = {};
  lists.forEach(({ data }, i) => {
    const f = data?.[0];
    const type = GENERAL_DOCS[i].type;
    if (f?.id) out[type] = { path: `${folder(id, type)}/${f.name}`, size: f.metadata?.size ?? 0, uploadedAt: f.created_at ?? "" };
  });
  return out;
}

export async function uploadGeneralDoc(type: DocType, file: File): Promise<StoredDoc> {
  if (!ACCEPT.split(",").includes(file.type)) throw new Error("Use a PDF, JPG, PNG or WEBP file.");
  if (file.size > MAX_BYTES) throw new Error("Files must be 10 MB or smaller.");
  if (!(await ensureConsent("documents"))) throw new Error(NO_CONSENT.documents);
  // The user's file name is not kept in the path: it can hold personal details.
  const ext = file.type === "application/pdf" ? "pdf" : file.type.split("/")[1];
  const path = `${folder(await uid(), type)}/${Date.now()}.${ext}`;
  const { error } = await createClient().storage.from(BUCKET).upload(path, file, { contentType: file.type });
  if (error) throw new Error("Upload failed. Please try again.");
  return { path, size: file.size, uploadedAt: new Date().toISOString() };
}

export async function viewUrl(path: string): Promise<string | null> {
  const { data } = await createClient().storage.from(BUCKET).createSignedUrl(path, 60);
  return data?.signedUrl ?? null;
}

export type { DocType };
