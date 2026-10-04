"use client";

import { ArrowLeft, RotateCcw, ShieldAlert, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { api } from "@/lib/api";
import { createClient } from "@/lib/supabase/client";
import { cn } from "@/lib/utils";

type Event = { id: number; actor: string; action: string; hash: string; payload: Record<string, unknown> | null; created_at: string };
type Audit = { events: Event[]; verified: boolean; broken: number[] };

const ACTION: Record<string, string> = {
  "profile.confirmed": "Profile details confirmed",
  "profile.rejected": "Profile suggestion declined",
  "form.set": "Scholarship chosen",
  "phase.changed": "Step changed",
  "document.uploaded": "Document uploaded",
  "flag.raised": "Problem found",
  "flag.resolved": "Problem resolved",
  "flag.acknowledged": "Problem kept as is",
  "llm.sensitive_fallback": "Read by the backup AI service",
};
const ACTOR: Record<string, string> = { user: "You", agent: "Aster", system: "System" };

/** Field names, ids and steps only: the audit trail never holds the values themselves. */
function details(p: Event["payload"]): string {
  if (!p) return "";
  return Object.entries(p)
    .filter(([k, v]) => v !== null && v !== "" && !k.endsWith("_id") && !(Array.isArray(v) && !v.length))
    .map(([k, v]) => `${k.replaceAll("_", " ")}: ${Array.isArray(v) ? v.join(", ") : typeof v === "object" ? JSON.stringify(v) : String(v)}`)
    .join(" · ");
}

/** One session's audit trail; the backend recomputes the hash chain on every load. */
export default function AuditPage() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const [audit, setAudit] = useState<Audit | null>(null);
  const [scheme, setScheme] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api<Audit>("GET", `/api/sessions/${sessionId}/audit`).then(setAudit, (e: Error) => setError(e.message));
    void createClient()
      .from("form_sessions")
      .select("scheme_name")
      .eq("id", sessionId)
      .maybeSingle()
      .then(({ data }) => setScheme(data?.scheme_name ?? null));
  }, [sessionId]);
  useEffect(load, [load]);

  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-6 px-4 py-8 sm:px-8 sm:py-10">
      <Link href="/sessions" className="flex w-fit items-center gap-2 text-sm font-medium text-primary hover:underline">
        <ArrowLeft className="size-4" /> All applications
      </Link>
      <div>
        <span className="eyebrow">Audit trail</span>
        <h1 className="mt-2 text-3xl font-bold">{scheme || "Your application"}</h1>
        <p className="mt-2 text-muted-foreground">Every step is linked to the one before it by a hash, so a changed or deleted record shows up.</p>
      </div>

      {error ? (
        <div role="alert" className="card flex flex-wrap items-center gap-4 p-6">
          <p className="flex-1">Couldn&apos;t load the audit trail: {error}</p>
          <button type="button" className="btn-subtle" onClick={() => {
              setError(null);
              load();
            }}>
            <RotateCcw className="size-4" /> Try again
          </button>
        </div>
      ) : !audit ? (
        <p role="status" className="text-muted-foreground">
          Checking the record…
        </p>
      ) : (
        <>
          <div
            role="status"
            className={cn("flex items-center gap-3 rounded-2xl p-4 font-medium", audit.verified ? "bg-sage text-primary" : "bg-[#fde8e8] text-destructive")}
          >
            {audit.verified ? <ShieldCheck aria-hidden className="size-5" /> : <ShieldAlert aria-hidden className="size-5" />}
            {audit.verified
              ? `Record intact: all ${audit.events.length} steps check out.`
              : `Record changed: ${audit.broken.length} step(s) don't match their hash.`}
          </div>
          {audit.events.length === 0 ? (
            <p className="card p-6 text-muted-foreground">Nothing recorded for this application yet.</p>
          ) : (
            <ol className="card divide-y divide-border">
              {audit.events.map((e) => {
                const bad = audit.broken.includes(e.id);
                return (
                  <li key={e.id} className={cn("flex flex-col gap-1 p-4 sm:flex-row sm:gap-4", bad && "bg-[#fde8e8]")}>
                    <time dateTime={e.created_at} className="shrink-0 text-sm text-muted-foreground sm:w-40">
                      {new Date(e.created_at.replace(" ", "T").replace(/\+00$/, "Z")).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" })}
                    </time>
                    <div className="min-w-0 flex-1">
                      <p className="font-medium">
                        {ACTION[e.action] ?? e.action} <span className="text-sm font-normal text-muted-foreground">· {ACTOR[e.actor] ?? e.actor}</span>
                        {bad && <strong className="ml-2 text-sm text-destructive">doesn&apos;t match</strong>}
                      </p>
                      <p className="break-words text-sm text-muted-foreground">{details(e.payload)}</p>
                    </div>
                    <code title={e.hash} className="hidden shrink-0 self-center text-xs text-muted-foreground sm:block">
                      {e.hash.slice(0, 10)}
                    </code>
                  </li>
                );
              })}
            </ol>
          )}
        </>
      )}
    </div>
  );
}
