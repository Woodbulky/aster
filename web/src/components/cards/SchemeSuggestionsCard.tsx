"use client";

import { Check, GraduationCap } from "lucide-react";
import { useState } from "react";

import type { SchemeOption, SchemeSuggestionsPayload } from "@/lib/ws/protocol";

export function SchemeSuggestionsCard({
  payload,
  onPick,
}: {
  payload: SchemeSuggestionsPayload;
  onPick: (o: SchemeOption) => boolean;
}) {
  const [picked, setPicked] = useState<string | null>(null);
  return (
    <section aria-label="Choose a scholarship" className="card max-w-md p-5">
      <h2 className="flex items-center gap-2 font-heading font-semibold">
        <GraduationCap className="size-5 text-primary" /> Choose a scholarship
      </h2>
      <ul className="mt-4 flex flex-col gap-2">
        {payload.options.map((o) => (
          <li key={o.scheme_key}>
            <button
              disabled={picked !== null}
              onClick={() => onPick(o) && setPicked(o.scheme_key)}
              className="flex min-h-12 w-full items-center justify-between gap-3 rounded-xl border border-border px-4 py-3 text-left transition-colors hover:bg-[#f7f9f3] disabled:opacity-70"
            >
              <span className="min-w-0">
                <span className="block font-medium">{o.name}</span>
                <span className="mt-1 flex flex-wrap gap-1.5 text-xs">
                  <span className="chip bg-sage">{o.met} meet</span>
                  {o.not_met > 0 && <span className="chip bg-[#fde8e8]">{o.not_met} do not meet</span>}
                  {o.unknown > 0 && <span className="chip bg-[#fdf3dc]">{o.unknown} to confirm</span>}
                  {o.draft && <span className="chip bg-peach">Draft</span>}
                </span>
              </span>
              {picked === o.scheme_key && <Check className="size-4 shrink-0 text-primary" />}
            </button>
          </li>
        ))}
      </ul>
      <p className="mt-3 text-xs text-muted-foreground">{payload.note}</p>
    </section>
  );
}
