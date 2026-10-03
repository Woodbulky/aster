"use client";

import { CheckCircle2, ClipboardCheck, OctagonAlert, TriangleAlert } from "lucide-react";

import { cn } from "@/lib/utils";
import type { ReadinessPayload } from "@/lib/ws/protocol";

/** Ready = nothing blocking is open. Lists every value the form will use and where it came from. */
export function ReadinessCard({ payload }: { payload: ReadinessPayload }) {
  const p = payload;
  return (
    <section aria-label="Readiness check" className={cn("card max-w-xl border-l-4 p-5", p.ready ? "border-l-primary" : "border-l-destructive")}>
      <h3 className="flex items-start gap-2 font-heading font-semibold">
        {p.ready ? <CheckCircle2 className="mt-0.5 size-5 text-primary" /> : <OctagonAlert className="mt-0.5 size-5 text-destructive" />}
        {p.ready ? "Your documents are checked" : `${p.open_block.length} thing${p.open_block.length === 1 ? "" : "s"} still need your answer`}
      </h3>
      <div className="mt-2 flex flex-wrap gap-1.5 text-xs">
        <span className="chip bg-sage">{p.fields.length} values with sources</span>
        <span className="chip bg-muted">{p.documents.length} documents read</span>
        {p.open_warn.length > 0 && <span className="chip bg-[#fdf3dc]">{p.open_warn.length} to check</span>}
        {p.acknowledged.length > 0 && <span className="chip bg-muted">{p.acknowledged.length} kept as is</span>}
      </div>
      {p.open_block.length > 0 && (
        <ul className="mt-3 flex flex-col gap-1 text-sm">
          {p.open_block.map((f) => (
            <li key={f.flag_id} className="flex items-start gap-1.5 text-destructive">
              <OctagonAlert className="mt-0.5 size-4 shrink-0" /> {f.field}: {f.values.join(" vs ") || f.message}
            </li>
          ))}
        </ul>
      )}
      {p.acknowledged.length > 0 && (
        <ul className="mt-3 flex flex-col gap-1 text-sm text-muted-foreground">
          {p.acknowledged.map((f) => (
            <li key={f.flag_id} className="flex items-start gap-1.5">
              <TriangleAlert className="mt-0.5 size-4 shrink-0 text-[#b7791f]" /> {f.field} kept as is — “{f.reason}”
            </li>
          ))}
        </ul>
      )}
      <details className="mt-3 text-sm">
        <summary className="flex cursor-pointer items-center gap-1.5 text-primary">
          <ClipboardCheck className="size-4" /> Values for the form
        </summary>
        <dl className="mt-2 divide-y divide-border">
          {p.fields.map((f) => (
            <div key={f.field_key} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2">
              <dt className="w-40 shrink-0 text-muted-foreground">{f.label}</dt>
              <dd className="min-w-0 flex-1 font-medium break-words">{f.value}</dd>
              <dd className={cn("chip", f.confirmed ? "bg-sage text-primary" : "bg-muted text-muted-foreground")}>{f.source}</dd>
            </div>
          ))}
        </dl>
      </details>
      <p className="mt-3 text-xs text-muted-foreground">{p.note}</p>
    </section>
  );
}
