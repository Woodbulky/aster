"use client";

import { CheckCircle2, ExternalLink, FileUp, LoaderCircle, RotateCcw, TriangleAlert } from "lucide-react";
import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import { BLUR_MIN, blurScore } from "@/lib/blur";
import { ACCEPT } from "@/lib/general-docs";
import { sessionDocStatus, uploadSessionDoc, waitForDocument } from "@/lib/documents";
import { cn } from "@/lib/utils";
import type { ChecklistItem, DocStatus, DocumentChecklistPayload } from "@/lib/ws/protocol";

type Local = DocStatus | "uploading";

// Vault reuse is tried once per session+type, even if the card remounts.
const reused = new Set<string>();

const CHIP: Record<Local, { text: string; tone: string }> = {
  missing: { text: "To upload", tone: "bg-muted text-muted-foreground" },
  uploading: { text: "Uploading…", tone: "bg-butter" },
  uploaded: { text: "Reading…", tone: "bg-butter" },
  processing: { text: "Reading…", tone: "bg-butter" },
  extracted: { text: "Read", tone: "bg-sage text-primary" },
  failed: { text: "Couldn't read", tone: "bg-[#fde8e8] text-destructive" },
};

function host(url: string) {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

/** Upload slots for the scheme's documents. The chips follow the document row; when it has been
 * read, the server itself tells the conversation (field review card + summary). */
export function DocumentChecklistCard({ payload }: { payload: DocumentChecklistPayload }) {
  const [status, setStatus] = useState<Record<string, Local>>(() => Object.fromEntries(payload.items.map((i) => [i.doc_type, i.status])));
  const [error, setError] = useState<Record<string, string>>({});
  // A photo that looks blurry waits here until the user picks "use anyway" or another photo.
  const [blurry, setBlurry] = useState<{ type: string; file: File; score: number } | null>(null);

  useEffect(() => {
    // The card is a snapshot from when it was shown: refresh from the database.
    sessionDocStatus(payload.session_id)
      .then((docs) => {
        setStatus((s) => ({ ...s, ...Object.fromEntries(Object.entries(docs).map(([t, d]) => [t, d.status])) }));
        // Anything already saved in the profile vault is reused instead of asked for again.
        for (const item of payload.items) {
          if (docs[item.doc_type] || reused.has(`${payload.session_id}:${item.doc_type}`)) continue;
          reused.add(`${payload.session_id}:${item.doc_type}`);
          api<{ document_id?: string }>("POST", `/api/sessions/${payload.session_id}/documents/from-vault`, { doc_type: item.doc_type })
            .then((r) => {
              if (!r.document_id) return;
              setStatus((s) => ({ ...s, [item.doc_type]: "uploaded" }));
              const set = (st: DocStatus) => setStatus((x) => ({ ...x, [item.doc_type]: st }));
              return waitForDocument(r.document_id, set);
            })
            .catch(() => {}); // 404: nothing saved, the slot stays "To upload"
        }
      })
      .catch(() => {});
  }, [payload.session_id, payload.items]);

  async function pick(item: ChecklistItem, file: File | undefined, checked = false) {
    if (!file) return;
    setBlurry(null);
    const score = await blurScore(file);
    if (!checked && score !== null && score < BLUR_MIN) {
      setBlurry({ type: item.doc_type, file, score });
      return;
    }
    const set = (s: Local) => setStatus((x) => ({ ...x, [item.doc_type]: s }));
    setError((e) => ({ ...e, [item.doc_type]: "" }));
    set("uploading");
    try {
      const quality = score === null ? undefined : { blur_var: score };
      const id = await uploadSessionDoc(payload.session_id, item.doc_type, file, quality);
      set(await waitForDocument(id, set));
    } catch (e) {
      set("missing");
      setError((x) => ({ ...x, [item.doc_type]: (e as Error).message }));
    }
  }

  return (
    <section aria-label={`Documents for ${payload.scheme}`} className="card max-w-xl p-5">
      <h2 className="flex items-start gap-2 font-heading font-semibold">
        <FileUp className="mt-0.5 size-5 shrink-0 text-primary" /> Documents for {payload.scheme}
      </h2>
      <p className="mt-1 text-sm text-muted-foreground">{payload.note}</p>
      <ul className="mt-3 divide-y divide-border">
        {payload.items.map((item) => {
          const s = status[item.doc_type] ?? "missing";
          const busy = s === "uploading" || s === "uploaded" || s === "processing";
          return (
            <li key={item.doc_type} className="flex flex-wrap items-center gap-3 py-3">
              <div className="min-w-0 flex-1">
                <p className="font-medium">
                  {item.label} {item.required && <span className="text-xs font-normal text-destructive">required</span>}
                </p>
                {item.source ? (
                  <a href={item.source.url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-xs text-primary underline-offset-2 hover:underline">
                    per {host(item.source.url)} <ExternalLink className="size-3" />
                  </a>
                ) : (
                  item.note && <p className="text-xs text-muted-foreground">{item.note}</p>
                )}
                {blurry?.type === item.doc_type && (
                  <div role="alert" className="mt-2 rounded-xl bg-butter px-3 py-2 text-sm">
                    This photo looks blurry, so Aster may misread it. Take a clearer photo in good light, or use it anyway.
                    <button type="button" onClick={() => void pick(item, blurry.file, true)} className="ml-2 font-medium text-primary underline-offset-2 hover:underline">
                      Use anyway
                    </button>
                  </div>
                )}
                {error[item.doc_type] && (
                  <p role="alert" className="mt-1 text-xs text-destructive">
                    {error[item.doc_type]}
                  </p>
                )}
              </div>
              <span className={cn("chip", CHIP[s].tone)}>
                {busy && <LoaderCircle className="size-3.5 animate-spin" />}
                {s === "extracted" && <CheckCircle2 className="size-3.5" />}
                {s === "failed" && <TriangleAlert className="size-3.5" />}
                {CHIP[s].text}
              </span>
              <label className={cn("btn-ghost h-9 cursor-pointer px-3 text-sm", busy && "pointer-events-none opacity-50")}>
                {s === "missing" ? <FileUp className="size-4" /> : <RotateCcw className="size-4" />}
                {s === "missing" ? "Upload" : "Replace"}
                <input
                  type="file"
                  accept={ACCEPT}
                  className="sr-only"
                  disabled={busy}
                  aria-label={`Upload ${item.label}`}
                  onChange={(e) => {
                    void pick(item, e.target.files?.[0]);
                    e.target.value = "";
                  }}
                />
              </label>
            </li>
          );
        })}
      </ul>
      {payload.others.length > 0 && (
        <details className="mt-2 text-sm">
          <summary className="cursor-pointer text-primary">Also keep ready ({payload.others.length})</summary>
          <ul className="mt-1 list-disc pl-5 text-muted-foreground">
            {payload.others.map((o) => (
              <li key={o}>{o}</li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}
