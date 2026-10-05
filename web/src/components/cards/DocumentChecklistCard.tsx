"use client";

import { CheckCircle2, ExternalLink, FileUp, HelpCircle, LoaderCircle, RotateCcw, TriangleAlert } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { api, ensureConsent } from "@/lib/api";
import { BLUR_MIN, blurScore } from "@/lib/blur";
import { ACCEPT } from "@/lib/general-docs";
import { answerRequirement, docFor, sessionDocs, uploadSessionDoc, waitForDocument } from "@/lib/documents";
import { cn } from "@/lib/utils";
import type { ChecklistItem, DocStatus, DocumentChecklistPayload, RequirementQuestion } from "@/lib/ws/protocol";

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
const HOLDER = { student: null, parent: "a parent's document", either: "yours or a parent's" } as const;
const LATER = { apply: "", institute: "Your college asks for this", later: "Asked after you apply" } as const;

function host(url: string) {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);
const isQuestion = (a: ChecklistItem["ask"]): a is RequirementQuestion => !!a && "id" in a;

/** One row per scheme requirement. A requirement whose condition is unknown asks its question
 * here (never silently optional); the answer is saved with this tap as its source. The chips
 * follow the document row; when it has been read, the server tells the conversation itself. */
export function DocumentChecklistCard({ payload: saved, lang, onAnswered }: { payload: DocumentChecklistPayload; lang: string; onAnswered: () => void }) {
  // Cards saved in chat history before doc_types/type_labels existed lack them.
  const payload = useMemo(
    () => ({
      ...saved,
      items: saved.items.map((i) => ({ ...i, doc_types: i.doc_types ?? [i.doc_type], type_labels: i.type_labels ?? [i.label] })),
    }),
    [saved],
  );
  const [items, setItems] = useState<ChecklistItem[]>(payload.items);
  const [status, setStatus] = useState<Record<string, Local>>(() => Object.fromEntries(payload.items.map((i) => [i.id, i.status])));
  const [kind, setKind] = useState<Record<string, string>>({}); // which accepted type is being uploaded
  const [error, setError] = useState<Record<string, string>>({});
  const [asking, setAsking] = useState<string | null>(null);
  // A photo that looks blurry waits here until the user picks "use anyway" or another photo.
  const [blurry, setBlurry] = useState<{ id: string; file: File; score: number } | null>(null);

  useEffect(() => {
    // The card is a snapshot from when it was shown: refresh from the database.
    sessionDocs(payload.session_id)
      .then(async (docs) => {
        setStatus((s) => ({ ...s, ...Object.fromEntries(payload.items.flatMap((i) => (docFor(i, docs) ? [[i.id, docFor(i, docs)!.status]] : []))) }));
        // Anything already given (profile vault, or read in another application) is reused
        // instead of asked for again. The backend reads it only with document consent: ask once
        // here, or every reuse is a silent 403 (seen live: vault saved before consent existed).
        const todo = payload.items.filter(
          (i) => i.doc_type !== "other" && i.need !== "not_needed" && !docFor(i, docs) && !reused.has(`${payload.session_id}:${i.doc_type}`),
        );
        if (!todo.length || !(await ensureConsent("documents"))) return;
        for (const item of todo) {
          reused.add(`${payload.session_id}:${item.doc_type}`);
          api<{ document_id?: string }>("POST", `/api/sessions/${payload.session_id}/documents/from-vault`, { doc_type: item.doc_type })
            .then((r) => {
              if (!r.document_id) return;
              const set = (st: Local) => setStatus((x) => ({ ...x, [item.id]: st }));
              set("uploaded");
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
      setBlurry({ id: item.id, file, score });
      return;
    }
    const set = (s: Local) => setStatus((x) => ({ ...x, [item.id]: s }));
    setError((e) => ({ ...e, [item.id]: "" }));
    set("uploading");
    try {
      const quality = score === null ? undefined : { blur_var: score };
      const id = await uploadSessionDoc(payload.session_id, kind[item.id] ?? item.doc_type, file, quality, item.id);
      set(await waitForDocument(id, set));
    } catch (e) {
      set("missing");
      setError((x) => ({ ...x, [item.id]: (e as Error).message }));
    }
  }

  async function answer(item: ChecklistItem, q: RequirementQuestion, option: string) {
    setAsking(item.id);
    setError((e) => ({ ...e, [item.id]: "" }));
    try {
      setItems(await answerRequirement(payload.session_id, q.id, option, lang));
      onAnswered();
    } catch (e) {
      setError((x) => ({ ...x, [item.id]: (e as Error).message }));
    } finally {
      setAsking(null);
    }
  }

  const shown = items.filter((i) => i.need !== "not_needed");
  const skipped = items.filter((i) => i.need === "not_needed");
  return (
    <section aria-label={`Documents for ${payload.scheme}`} className="card max-w-xl p-5">
      <h2 className="flex items-start gap-2 font-heading font-semibold">
        <FileUp className="mt-0.5 size-5 shrink-0 text-primary" /> Documents for {payload.scheme}
      </h2>
      <p className="mt-1 text-sm text-muted-foreground">{payload.note}</p>
      <ul className="mt-3 divide-y divide-border">
        {shown.map((item) => {
          const s = status[item.id] ?? "missing";
          const busy = s === "uploading" || s === "uploaded" || s === "processing";
          const later = item.need === "later";
          const q = item.need === "ask" && s !== "extracted" && isQuestion(item.ask) ? item.ask : null;
          const detail = [item.period, HOLDER[item.holder]].filter(Boolean).join(" · ");
          return (
            <li key={item.id} className={cn("flex flex-wrap items-center gap-3 py-3", later && "opacity-70")}>
              <div className="min-w-0 flex-1">
                <p className="font-medium">
                  {item.label} {item.need === "required" && <span className="text-xs font-normal text-destructive">required</span>}
                  {item.need === "ask" && <span className="text-xs font-normal text-[#b7791f]">maybe needed</span>}
                </p>
                {detail && <p className="text-xs text-muted-foreground">{detail}</p>}
                {item.type_labels.length > 1 && <p className="text-xs text-muted-foreground">Any one of: {item.type_labels.join(" or ")}</p>}
                {later && <p className="text-xs text-muted-foreground">{LATER[item.stage]}</p>}
                {item.source ? (
                  <a href={item.source.url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-xs text-primary underline-offset-2 hover:underline">
                    per {host(item.source.url)} <ExternalLink className="size-3" />
                  </a>
                ) : null}
                {item.note && <p className="text-xs text-muted-foreground">{item.note}</p>}
                {q && (
                  <div className="mt-2 rounded-xl bg-butter/60 px-3 py-2 text-sm" role="group" aria-label={q.text}>
                    <p className="flex items-start gap-1.5">
                      <HelpCircle className="mt-0.5 size-4 shrink-0 text-[#b7791f]" />
                      <span>{q.text}</span>
                    </p>
                    <div className="mt-2 flex flex-wrap gap-2">
                      {q.options.map((o) => (
                        <button key={o} type="button" disabled={asking !== null} onClick={() => void answer(item, q, o)} className="btn-ghost h-8 px-3 text-sm">
                          {asking === item.id && <LoaderCircle className="size-3.5 animate-spin" />} {cap(o)}
                        </button>
                      ))}
                    </div>
                  </div>
                )}
                {item.need === "ask" && item.ask && !isQuestion(item.ask) && item.ask.profile_field && (
                  <p className="mt-1 text-xs text-[#b7791f]">Add your {item.ask.profile_field.replaceAll("_", " ")} to your profile to know if this is needed.</p>
                )}
                {blurry?.id === item.id && (
                  <div role="alert" className="mt-2 rounded-xl bg-butter px-3 py-2 text-sm">
                    This photo looks blurry, so Aster may misread it. Take a clearer photo in good light, or use it anyway.
                    <button type="button" onClick={() => void pick(item, blurry.file, true)} className="ml-2 font-medium text-primary underline-offset-2 hover:underline">
                      Use anyway
                    </button>
                  </div>
                )}
                {error[item.id] && (
                  <p role="alert" className="mt-1 text-xs text-destructive">
                    {error[item.id]}
                  </p>
                )}
              </div>
              <span className={cn("chip", CHIP[s].tone)}>
                {busy && <LoaderCircle className="size-3.5 animate-spin" />}
                {s === "extracted" && <CheckCircle2 className="size-3.5" />}
                {s === "failed" && <TriangleAlert className="size-3.5" />}
                {CHIP[s].text}
              </span>
              {item.doc_types.length > 1 && s === "missing" && (
                <select
                  aria-label={`Which document for ${item.label}`}
                  value={kind[item.id] ?? item.doc_type}
                  onChange={(e) => setKind((k) => ({ ...k, [item.id]: e.target.value }))}
                  className="h-9 rounded-lg border border-input bg-background px-2 text-sm"
                >
                  {item.doc_types.map((t, i) => (
                    <option key={t} value={t}>
                      {item.type_labels[i]}
                    </option>
                  ))}
                </select>
              )}
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
      {skipped.length > 0 && (
        <details className="mt-2 text-sm">
          <summary className="cursor-pointer text-primary">Not needed for you ({skipped.length})</summary>
          <ul className="mt-1 list-disc pl-5 text-muted-foreground">
            {skipped.map((i) => (
              <li key={i.id}>{i.label}</li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}
