"use client";

import { CheckCircle2, Eye, FileText, LoaderCircle, RefreshCw, Upload } from "lucide-react";
import { useEffect, useState } from "react";

import {
  ACCEPT,
  type DocType,
  GENERAL_DOCS,
  listGeneralDocs,
  type StoredDoc,
  uploadGeneralDoc,
  viewUrl,
} from "@/lib/general-docs";
import { cn } from "@/lib/utils";

const fmtSize = (b: number) => (b >= 1024 * 1024 ? `${(b / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(b / 1024))} KB`);
const fmtDate = (iso: string) => !iso ? "" : new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });

/** General documents: each file saves to the user's private storage the moment it is picked. */
export function DocVault({ onCount }: { onCount?: (n: number) => void }) {
  const [docs, setDocs] = useState<Partial<Record<DocType, StoredDoc>> | null>(null);
  const [busy, setBusy] = useState<DocType | null>(null);
  const [error, setError] = useState<{ type: DocType | null; text: string } | null>(null);

  useEffect(() => {
    listGeneralDocs()
      .then(setDocs)
      .catch(() => {
        setDocs({});
        setError({ type: null, text: "Couldn't load your documents. Check your connection and refresh." });
      });
  }, []);

  useEffect(() => {
    if (docs) onCount?.(Object.keys(docs).length);
  }, [docs, onCount]);

  async function pick(type: DocType, file: File | undefined) {
    if (!file) return;
    setBusy(type);
    setError(null);
    try {
      const saved = await uploadGeneralDoc(type, file);
      setDocs((d) => ({ ...d, [type]: saved }));
    } catch (e) {
      setError({ type, text: (e as Error).message });
    } finally {
      setBusy(null);
    }
  }

  async function view(path: string) {
    const w = window.open("", "_blank"); // open synchronously so popup blockers allow it
    const url = await viewUrl(path);
    if (w && url) {
      w.opener = null;
      w.location.href = url;
    } else w?.close();
  }

  return (
    <div className="flex flex-col gap-3">
      {error?.type === null && (
        <p role="alert" className="rounded-xl bg-destructive/10 p-3 text-sm text-destructive">
          {error.text}
        </p>
      )}
      <ul className="grid gap-3">
        {GENERAL_DOCS.map((d) => {
          const saved = docs?.[d.type];
          const inputId = `doc-${d.type}`;
          return (
            <li key={d.type} className="card flex flex-wrap items-center gap-4 p-4">
              <span className={cn("flex size-11 shrink-0 items-center justify-center rounded-xl text-primary", saved ? "bg-sage" : "bg-muted")}>
                <FileText className="size-5" />
              </span>
              <div className="min-w-0 flex-1">
                <p className="font-semibold">{d.label}</p>
                <p className="text-sm text-muted-foreground">
                  {docs === null ? (
                    "Checking…"
                  ) : saved ? (
                    <span className="inline-flex items-center gap-1.5 text-primary">
                      <CheckCircle2 className="size-3.5" /> Saved {fmtDate(saved.uploadedAt)}
                      {saved.size > 0 && <span className="text-muted-foreground">· {fmtSize(saved.size)}</span>}
                    </span>
                  ) : (
                    d.hint
                  )}
                </p>
                {error?.type === d.type && (
                  <p role="alert" className="mt-1 text-sm text-destructive">
                    {error.text}
                  </p>
                )}
              </div>
              <div className="flex items-center gap-2">
                {saved && (
                  <button type="button" onClick={() => view(saved.path)} className="btn-ghost h-10" aria-label={`View ${d.label}`}>
                    <Eye className="size-4" /> View
                  </button>
                )}
                <input
                  id={inputId}
                  type="file"
                  accept={ACCEPT}
                  className="peer sr-only"
                  disabled={busy !== null || docs === null}
                  onChange={(e) => {
                    void pick(d.type, e.target.files?.[0]);
                    e.target.value = "";
                  }}
                />
                <label
                  htmlFor={inputId}
                  className={cn(
                    saved ? "btn-subtle" : "btn-primary",
                    "h-10 cursor-pointer px-4 text-sm peer-focus-visible:ring-2 peer-focus-visible:ring-ring",
                    (busy !== null || docs === null) && "pointer-events-none opacity-50",
                  )}
                >
                  {busy === d.type ? (
                    <LoaderCircle className="size-4 animate-spin" />
                  ) : saved ? (
                    <RefreshCw className="size-4" />
                  ) : (
                    <Upload className="size-4" />
                  )}
                  {busy === d.type ? "Saving…" : saved ? "Replace" : "Upload"}
                </label>
              </div>
            </li>
          );
        })}
      </ul>
      <p className="text-xs text-muted-foreground">PDF, JPG, PNG or WEBP · up to 10 MB · stored privately in your account.</p>
    </div>
  );
}
