"use client";

import { ArrowRight, History, RotateCcw, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { createClient } from "@/lib/supabase/client";

type Session = { id: string; scheme_name: string | null; portal: string | null; phase: string; status: string; created_at: string };

const PHASE_LABEL: Record<string, string> = {
  onboarding: "Getting to know you",
  choose_form: "Choosing a scholarship",
  research: "Researching the rules",
  eligibility: "Eligibility checked",
  documents: "Collecting documents",
  verification: "Checking documents",
  ready: "Ready to fill",
  form_fill: "Filling the form",
  done: "Finished",
};

const fmtDate = (iso: string) => new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });

/** Past and current form sessions (RLS read), each with its conversation and audit trail. */
export default function SessionsPage() {
  const [sessions, setSessions] = useState<Session[] | null>(null);
  const [error, setError] = useState(false);
  const load = useCallback(() => {
    createClient()
      .from("form_sessions")
      .select("id, scheme_name, portal, phase, status, created_at")
      .order("created_at", { ascending: false })
      .then(({ data, error }) => {
        if (error) setError(true);
        else setSessions(data);
      });
  }, []);
  useEffect(load, [load]);

  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-8 px-4 py-8 sm:px-8 sm:py-10">
      <div>
        <span className="eyebrow">Everything on record</span>
        <h1 className="mt-2 text-3xl font-bold sm:text-4xl">Your applications.</h1>
        <p className="mt-2 text-muted-foreground">Each scholarship you worked on, with a tamper-evident record of every step.</p>
      </div>
      {error ? (
        <div role="alert" className="card flex flex-wrap items-center gap-4 p-6">
          <p className="flex-1">Couldn&apos;t load your applications. Check your connection.</p>
          <button type="button" className="btn-subtle" onClick={() => {
              setError(false);
              load();
            }}>
            <RotateCcw className="size-4" /> Try again
          </button>
        </div>
      ) : sessions === null ? (
        <p role="status" className="text-muted-foreground">
          Loading…
        </p>
      ) : sessions.length === 0 ? (
        <div className="card flex flex-col items-center gap-3 p-10 text-center">
          <History aria-hidden className="size-8 text-muted-foreground" />
          <h2 className="text-lg font-bold">No applications yet</h2>
          <p className="text-muted-foreground">Start a conversation and pick a scholarship. It will show up here.</p>
          <Link href="/chat" className="btn-primary mt-2">
            Start <ArrowRight className="size-4" />
          </Link>
        </div>
      ) : (
        <ul className="flex flex-col gap-4">
          {sessions.map((s) => (
            <li key={s.id} className="card flex flex-wrap items-center gap-4 p-5">
              <div className="min-w-0 flex-1">
                <h2 className="truncate font-heading font-semibold">{s.scheme_name || "No scholarship chosen yet"}</h2>
                <p className="mt-1 text-sm text-muted-foreground">
                  {PHASE_LABEL[s.phase] ?? s.phase} · started {fmtDate(s.created_at)}
                  {s.portal ? ` · ${s.portal.toUpperCase()}` : ""}
                </p>
              </div>
              <Link href={`/sessions/${s.id}`} className="btn-subtle text-sm">
                <ShieldCheck className="size-4" /> Audit trail
              </Link>
              <Link href={`/chat/${s.id}`} className="btn-primary text-sm">
                Open <ArrowRight className="size-4" />
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
