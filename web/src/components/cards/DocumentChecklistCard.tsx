"use client";

import { CheckCircle2, ExternalLink, FileUp, LoaderCircle, RotateCcw, TriangleAlert } from "lucide-react";
import { useEffect, useState } from "react";

import { ACCEPT } from "@/lib/general-docs";
import { sessionDocStatus, uploadSessionDoc, waitForDocument } from "@/lib/documents";
import { cn } from "@/lib/utils";
import type { ChecklistItem, DocStatus, DocumentChecklistPayload } from "@/lib/ws/protocol";

type Local = DocStatus | "uploading";

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

/** Upload slots for the scheme's documents. When a document has been read, onProcessed tells the
 * conversation, which shows the field review card. */
export function DocumentChecklistCard({ payload, onProcessed }: { payload: DocumentChecklistPayload; onProcessed: (documentId: string) => void }) {
  const [status, setStatus] = useState<Record<string, Local>>(() => Object.fromEntries(payload.items.map((i) => [i.doc_type, i.status])));
  const [error, setError] = useState<Record<string, string>>({});

  useEffect(() => {
    // The card is a snapshot from when it was shown: refresh from the database.
    sessionDocStatus(payload.session_id)
      .then((docs) => setStatus((s) => ({ ...s, ...Object.fromEntries(Object.entries(docs).map(([t, d]) => [t, d.status])) })))
      .catch(() => {});
  }, [payload.session_id]);

  async function pick(item: ChecklistItem, file: File | undefined) {
    if (!file) return;
    const set = (s: Local) => setStatus((x) => ({ ...x, [item.doc_type]: s }));
    setError((e) => ({ ...e, [item.doc_type]: "" }));
    set("uploading");
    try {
      const id = await uploadSessionDoc(payload.session_id, item.doc_type, file);
      const done = await waitForDocument(id, set);
      set(done);
      onProcessed(id);
    } catch (e) {
      set("missing");
      setError((x) => ({ ...x, [item.doc_type]: (e as Error).message }));
    }
  }

  return (
    <section aria-label={`Documents for ${payload.scheme}`} className="card max-w-xl p-5">
      <h3 className="flex items-start gap-2 font-heading font-semibold">
        <FileUp className="mt-0.5 size-5 shrink-0 text-primary" /> Documents for {payload.scheme}
      </h3>
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
