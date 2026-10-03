"use client";

import { CheckCircle2, ExternalLink, FileSearch, LoaderCircle, OctagonAlert, TriangleAlert } from "lucide-react";
import { useEffect, useState } from "react";

import { DocumentViewer } from "@/components/cards/FieldReviewCard";
import { answerFlag, flagState, type FlagState } from "@/lib/documents";
import { cn } from "@/lib/utils";
import type { BBox, FlagCandidate, FlagPayload } from "@/lib/ws/protocol";

const OTHER = "__other__";

function host(url: string) {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

/** One problem found across the user's sources. The user picks the right value (or types one)
 * and says why, or keeps it as is with a reason. Aster never picks (guardrail 3). */
export function FlagCard({ payload, onAnswered }: { payload: FlagPayload; onAnswered: (flagId: string) => void }) {
  const [state, setState] = useState<FlagState>({ status: payload.status, resolution: null });
  const [choice, setChoice] = useState<string>("");
  const [typed, setTyped] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [viewing, setViewing] = useState<FlagCandidate | null>(null);

  useEffect(() => {
    // The card is a snapshot: the flag may have been answered since (another tap, by voice).
    flagState(payload.flag_id).then((s) => s && setState(s), () => {});
  }, [payload.flag_id]);

  const block = payload.severity === "block";
  const open = state.status === "open";
  const value = choice === OTHER ? typed.trim() : "";
  const canSubmit = reason.trim().length >= 3 && !busy;

  async function submit(acknowledge: boolean) {
    setBusy(true);
    setError(null);
    try {
      const status = await answerFlag(payload.session_id, payload.flag_id, {
        reason: reason.trim(),
        ...(acknowledge ? {} : choice === OTHER ? { value } : { candidate_id: choice }),
      });
      const picked = payload.candidates.find((c) => c.id === choice)?.value;
      setState({
        status: status as FlagState["status"],
        resolution: { reason: reason.trim(), candidate_id: acknowledge || choice === OTHER ? null : choice, value: acknowledge ? undefined : choice === OTHER ? value : picked },
      });
      onAnswered(payload.flag_id);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const Icon = block ? OctagonAlert : TriangleAlert;
  return (
    <section
      aria-label={`Check needed: ${payload.field_label ?? "document"}`}
      className={cn("card max-w-xl border-l-4 p-5", !open ? "border-l-primary" : block ? "border-l-destructive" : "border-l-[#d69e2e]")}
    >
      <h3 className="flex items-start gap-2 font-heading font-semibold">
        {open ? <Icon className={cn("mt-0.5 size-5 shrink-0", block ? "text-destructive" : "text-[#b7791f]")} /> : <CheckCircle2 className="mt-0.5 size-5 shrink-0 text-primary" />}
        <span>
          {payload.type === "missing_doc" ? payload.doc?.label : payload.field_label}
          <span className="ml-2 align-middle text-xs font-normal text-muted-foreground">{!open ? "Answered" : block ? "Needs your answer" : "Worth checking"}</span>
        </span>
      </h3>
      <p className="mt-1 text-sm">{payload.message}</p>
      {payload.doc?.source && (
        <a href={payload.doc.source.url} target="_blank" rel="noopener noreferrer" className="mt-1 inline-flex items-center gap-1 text-xs text-primary underline-offset-2 hover:underline">
          Required per {host(payload.doc.source.url)} <ExternalLink className="size-3" />
        </a>
      )}

      {payload.candidates.length > 0 && (
        <fieldset className="mt-3" disabled={!open || busy}>
          <legend className="sr-only">Values found</legend>
          <ul className="flex flex-col gap-2">
            {payload.candidates.map((c) => {
              const chosen = state.resolution?.candidate_id === c.id;
              return (
                <li key={c.id} className={cn("flex flex-wrap items-center gap-3 rounded-xl border border-border px-3 py-2.5", (choice === c.id || chosen) && "border-primary bg-sage/40")}>
                  {payload.can_pick && open ? (
                    <input type="radio" name={`flag-${payload.flag_id}`} value={c.id} checked={choice === c.id} onChange={() => setChoice(c.id)} aria-label={`${c.value} from ${c.label}`} className="size-4 accent-primary" />
                  ) : (
                    chosen && <CheckCircle2 className="size-4 text-primary" aria-label="Chosen" />
                  )}
                  <strong className="min-w-0 flex-1 font-medium break-words">{c.value}</strong>
                  {c.page ? (
                    <button type="button" onClick={() => setViewing(c)} className="chip cursor-pointer bg-sage text-primary hover:ring-1 hover:ring-primary/40">
                      <FileSearch className="size-3.5" /> {c.label}
                    </button>
                  ) : (
                    <span className="chip bg-muted text-muted-foreground">{c.label}</span>
                  )}
                </li>
              );
            })}
            {payload.can_type && open && (
              <li className={cn("flex flex-wrap items-center gap-3 rounded-xl border border-border px-3 py-2.5", choice === OTHER && "border-primary bg-sage/40")}>
                <input type="radio" name={`flag-${payload.flag_id}`} value={OTHER} checked={choice === OTHER} onChange={() => setChoice(OTHER)} aria-label="Something else" className="size-4 accent-primary" />
                <input
                  value={typed}
                  onFocus={() => setChoice(OTHER)}
                  onChange={(e) => setTyped(e.target.value)}
                  maxLength={200}
                  placeholder="Something else — type the right value"
                  aria-label="The right value"
                  className="h-9 min-w-0 flex-1 rounded-lg border border-input bg-background px-3 text-sm outline-none focus:border-ring"
                />
              </li>
            )}
          </ul>
        </fieldset>
      )}

      {open ? (
        <div className="mt-3 flex flex-col gap-2">
          <label className="text-sm font-medium" htmlFor={`reason-${payload.flag_id}`}>
            Why? <span className="font-normal text-muted-foreground">(saved with your answer)</span>
          </label>
          <input
            id={`reason-${payload.flag_id}`}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            maxLength={300}
            placeholder={payload.type === "missing_doc" ? "e.g. I'll upload it tomorrow" : "e.g. the certificate is the latest one"}
            className="h-10 rounded-xl border border-input bg-background px-3 text-sm outline-none focus:border-ring"
          />
          {error && (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          )}
          <div className="flex flex-wrap gap-2">
            {(payload.can_pick || payload.can_type) && (
              <button type="button" disabled={!canSubmit || !choice || (choice === OTHER && !value)} onClick={() => void submit(false)} className="btn-primary h-10 px-4 text-sm">
                {busy && <LoaderCircle className="size-4 animate-spin" />} Use this value
              </button>
            )}
            <button type="button" disabled={!canSubmit} onClick={() => void submit(true)} className="btn-ghost h-10 px-4 text-sm">
              {block ? "Continue anyway" : "Keep as is"}
            </button>
          </div>
        </div>
      ) : (
        <p className="mt-3 flex items-center gap-1.5 text-sm text-primary">
          <CheckCircle2 className="size-4" />{" "}
          {state.status === "resolved" ? (
            <>
              Using <strong className="font-semibold">{state.resolution?.value ?? payload.candidates.find((c) => c.id === state.resolution?.candidate_id)?.value ?? "your choice"}</strong>
            </>
          ) : (
            "Kept as is"
          )}
          {state.resolution?.reason && <span className="text-muted-foreground">— “{state.resolution.reason}”</span>}
        </p>
      )}

      {viewing?.page && (
        <DocumentViewer
          title={`${payload.field_label}: ${viewing.value}`}
          page={viewing.page}
          boxes={viewing.bbox.filter((b): b is BBox => b !== null)}
          onClose={() => setViewing(null)}
        />
      )}
    </section>
  );
}
