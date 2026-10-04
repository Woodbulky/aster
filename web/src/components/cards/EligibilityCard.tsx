"use client";

import { ArrowRight, CalendarClock, CircleCheck, CircleHelp, CircleX, ExternalLink, ListChecks } from "lucide-react";

import { cn } from "@/lib/utils";
import type { CriterionResult, EligibilityPayload } from "@/lib/ws/protocol";

const STATUS = {
  met: { icon: CircleCheck, label: "Meets", tone: "text-primary" },
  not_met: { icon: CircleX, label: "Does not meet", tone: "text-destructive" },
  unknown: { icon: CircleHelp, label: "Unknown", tone: "text-[#b7791f]" },
} as const;

function host(url: string) {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

function Row({ r }: { r: CriterionResult }) {
  const s = STATUS[r.status];
  return (
    <li className="flex gap-3 py-3">
      <s.icon aria-label={s.label} className={cn("mt-0.5 size-5 shrink-0", s.tone)} />
      <div className="min-w-0 flex-1">
        <p className="font-medium">{r.text}</p>
        <p className="mt-0.5 text-sm text-muted-foreground">{r.reason}</p>
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
export function EligibilityCard({ payload, onContinue }: { payload: EligibilityPayload; onContinue?: () => void }) {
  const c = payload.counts;
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
        <span className="chip bg-[#fdf3dc]">{c.unknown} unknown</span>
      </div>
      <ul className="mt-2 divide-y divide-border">
        {payload.results.map((r) => (
          <Row key={r.id} r={r} />
        ))}
      </ul>
      {payload.deadlines.map((d) => (
        <p key={d.label} className={cn("mt-2 flex items-center gap-2 text-sm", d.passed && "text-destructive")}>
          <CalendarClock className="size-4" /> {d.label}: {d.date ?? "not stated"}
          {d.passed && " — this date has passed"}
        </p>
      ))}
      <p className="mt-3 text-xs text-muted-foreground">{payload.note}</p>
      {onContinue && (
        <button type="button" onClick={onContinue} className="btn-primary mt-4 h-10 px-4 text-sm">
          Continue to documents <ArrowRight className="size-4" />
        </button>
      )}
    </section>
  );
}
