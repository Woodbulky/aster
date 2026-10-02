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
    <section aria-label="Choose a form" className="card max-w-md p-5">
      <h3 className="flex items-center gap-2 font-heading font-semibold">
        <GraduationCap className="size-5 text-primary" /> Choose a form
      </h3>
      <ul className="mt-4 flex flex-col gap-2">
        {payload.options.map((o) => {
          const key = o.scheme_key ?? o.portal;
          return (
            <li key={key}>
              <button
                disabled={picked !== null}
                onClick={() => onPick(o) && setPicked(key)}
                className="flex min-h-12 w-full items-center justify-between gap-3 rounded-xl border border-border px-4 py-3 text-left font-medium transition-colors hover:bg-[#f7f9f3] disabled:opacity-70"
              >
                {o.name}
                {picked === key && <Check className="size-4 text-primary" />}
              </button>
            </li>
          );
        })}
      </ul>
      <p className="mt-3 text-xs text-muted-foreground">{payload.note}</p>
    </section>
  );
}
