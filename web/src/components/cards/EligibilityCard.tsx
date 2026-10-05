"use client";

import { ArrowRight, CalendarClock, CircleCheck, CircleHelp, CircleMinus, CircleX, ExternalLink, ListChecks, LoaderCircle } from "lucide-react";
import { useState } from "react";

import { answerEligibility } from "@/lib/documents";
import { cn } from "@/lib/utils";
import type { CriterionResult, EligibilityPayload } from "@/lib/ws/protocol";

const STATUS = {
  met: { icon: CircleCheck, label: "Meets", tone: "text-primary" },
  not_met: { icon: CircleX, label: "Does not meet", tone: "text-destructive" },
  unknown: { icon: CircleHelp, label: "Needs confirmation", tone: "text-[#b7791f]" },
  not_applicable: { icon: CircleMinus, label: "Not applicable", tone: "text-muted-foreground" },
} as const;

const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

function host(url: string) {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

function Row({ r, asking, error, onAnswer }: { r: CriterionResult; asking: boolean; error?: string; onAnswer: (questionId: string, option: string) => void }) {
  const s = STATUS[r.status];
  // One question at a time: the exact condition still unanswered (cards saved before `needs` have none).
  const ask = r.status === "unknown" ? (r.needs ?? []).find((n) => n.kind === "question") : undefined;
  return (
    <li className={cn("flex gap-3 py-3", r.status === "not_applicable" && "opacity-70")}>
      <s.icon aria-label={s.label} className={cn("mt-0.5 size-5 shrink-0", s.tone)} />
      <div className="min-w-0 flex-1">
        <p className="font-medium">{r.text}</p>
        <p className="mt-0.5 text-sm text-muted-foreground">{r.reason}</p>
        {ask && (
          <div className="mt-2 flex flex-wrap gap-2" role="group" aria-label={ask.text}>
            {ask.options.map((o) => (
              <button key={o} type="button" disabled={asking} onClick={() => onAnswer(ask.id, o)} className="btn-ghost h-8 px-3 text-sm">
                {asking && <LoaderCircle className="size-3.5 animate-spin" />} {cap(o)}
              </button>
            ))}
          </div>
        )}
        {error && (
          <p role="alert" className="mt-1 text-xs text-destructive">
            {error}
          </p>
        )}
        <details className="mt-1 text-sm">
          <summary className="cursor-pointer text-primary">Official text</summary>
          <blockquote className="mt-1 border-l-2 border-border pl-3 text-muted-foreground italic">“{r.source.quote}”</blockquote>
          <a href={r.source.url} target="_blank" rel="noopener noreferrer" className="mt-1 inline-flex items-center gap-1 text-primary underline-offset-2 hover:underline">
            {host(r.source.url)} <ExternalLink className="size-3.5" />
          </a>
        </details>
      </div>
    </li>
  );
}

/** Per-criterion met / not met / unknown with the official quote. Never a final verdict
 * (guardrail 1): the scheme authority decides. */
export function EligibilityCard({
  payload: saved,
  sessionId,
  lang,
  onContinue,
  onAnswered,
}: {
  payload: EligibilityPayload;
  sessionId: string;
  lang: string;
  onContinue?: () => void;
  onAnswered?: () => void;
}) {
  // A tap on a question replaces the card with the server's re-evaluation.
  const [fresh, setFresh] = useState<EligibilityPayload | null>(null);
  const payload = fresh ?? saved;
  const c = payload.counts;
  const [asking, setAsking] = useState<string | null>(null);
  const [error, setError] = useState<Record<string, string>>({});
  const [continued, setContinued] = useState(false); // a second tap would ask for a second checklist

  async function answer(r: CriterionResult, questionId: string, option: string) {
    setAsking(r.id);
    setError((e) => ({ ...e, [r.id]: "" }));
    try {
      setFresh(await answerEligibility(sessionId, questionId, option, lang));
      onAnswered?.();
    } catch (e) {
      setError((x) => ({ ...x, [r.id]: (e as Error).message }));
    } finally {
      setAsking(null);
    }
  }
  return (
    <section aria-label={`Eligibility check: ${payload.name}`} className="card max-w-xl p-5">
      <h2 className="flex items-start gap-2 font-heading font-semibold">
        <ListChecks className="mt-0.5 size-5 shrink-0 text-primary" />
        <span>{payload.name}</span>
      </h2>
      <div className="mt-2 flex flex-wrap gap-1.5">
        {payload.origin === "live" && <span className="chip bg-butter">Unverified · from the web</span>}
        {payload.draft && <span className="chip bg-peach">Draft rules · not yet verified</span>}
        <span className="chip bg-sage">{c.met} meet</span>
        <span className="chip bg-[#fde8e8]">{c.not_met} do not meet</span>
        <span className="chip bg-[#fdf3dc]">{c.unknown} need confirmation</span>
        {(c.not_applicable ?? 0) > 0 && <span className="chip bg-muted text-muted-foreground">{c.not_applicable} not applicable</span>}
      </div>
      <ul className="mt-2 divide-y divide-border">
        {payload.results.map((r) => (
          <Row key={r.id} r={r} asking={asking === r.id} error={error[r.id]} onAnswer={(q, o) => void answer(r, q, o)} />
        ))}
      </ul>
      {payload.deadlines.map((d) => (
        <p key={d.label} className={cn("mt-2 flex items-center gap-2 text-sm", d.passed && "text-destructive")}>
          <CalendarClock className="size-4" /> {d.label}: {d.date ?? "not stated"}
          {d.passed && " — this date has passed"}
          {d.unconfirmed_since && <span className="text-muted-foreground"> (last checked {d.unconfirmed_since}; confirm on the portal)</span>}
        </p>
      ))}
      {payload.checked && <p className="mt-3 text-xs text-muted-foreground">{payload.checked}</p>}
      <p className="mt-3 text-xs text-muted-foreground">{payload.note}</p>
      {onContinue && (
        <button
          type="button"
          disabled={continued}
          onClick={() => {
            setContinued(true);
            onContinue();
          }}
          className="btn-primary mt-4 h-10 px-4 text-sm"
        >
          Continue to documents <ArrowRight className="size-4" />
        </button>
      )}
    </section>
  );
}
