"use client";

import { ExternalLink, SearchCheck } from "lucide-react";

import type { ResearchItem, ResearchSummaryPayload } from "@/lib/ws/protocol";

function Items({ title, items }: { title: string; items: ResearchItem[] }) {
  if (!items.length) return null;
  return (
    <>
      <h3 className="mt-4 text-sm font-semibold">{title}</h3>
      <ul className="mt-1 divide-y divide-border">
        {items.map((it, i) => (
          <li key={i} className="py-2.5">
            <p className="font-medium">{it.text}</p>
            <p className="mt-0.5 text-xs text-muted-foreground">
              Unverified — from{" "}
              <a href={it.source_url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-0.5 text-primary hover:underline">
                {it.site} <ExternalLink className="size-3" />
              </a>{" "}
              on {it.fetched_on}
            </p>
            <blockquote className="mt-1 border-l-2 border-border pl-3 text-sm text-muted-foreground italic">“{it.quote}”</blockquote>
          </li>
        ))}
      </ul>
    </>
  );
}

/** Live research results: only items whose quote was found on the cited page reach this card. */
export function ResearchSummaryCard({ payload }: { payload: ResearchSummaryPayload }) {
  return (
    <section aria-label={`Research: ${payload.scheme}`} className="card max-w-xl p-5">
      <h2 className="flex items-start gap-2 font-heading font-semibold">
        <SearchCheck className="mt-0.5 size-5 shrink-0 text-primary" />
        <span>What I found: {payload.scheme}</span>
      </h2>
      <span className="chip mt-2 bg-butter">Unverified · from the web</span>
      <Items title="Eligibility rules" items={payload.eligibility} />
      <Items title="Documents" items={payload.documents} />
      {payload.rejected > 0 && (
        <p className="mt-3 text-xs text-muted-foreground">
          {payload.rejected} item{payload.rejected > 1 ? "s were" : " was"} left out because the quote was not on the cited page.
        </p>
      )}
      <p className="mt-2 text-xs text-muted-foreground">{payload.note} Check each rule at its source.</p>
    </section>
  );
}
