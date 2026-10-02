"use client";

import { Check, PencilLine, UserRoundCheck, X } from "lucide-react";
import { useState } from "react";

import { ALL_FIELDS } from "@/components/profile/ProfileForm";
import { confirmProfile, type ProfileDraft, type ProfileKey } from "@/lib/api";
import type { ConfirmProfilePayload } from "@/lib/ws/protocol";

const field = (k: string) => ALL_FIELDS.find((f) => f.key === k);

function show(k: string, v: string) {
  if (k === "annual_family_income" && v && !Number.isNaN(Number(v))) return `₹${Number(v).toLocaleString("en-IN")}`;
  return v || "—";
}

/** Guardrail 4: values heard in conversation are saved only when the user taps Confirm. */
export function ConfirmProfileCard({
  payload,
  onAnswered,
}: {
  payload: ConfirmProfilePayload;
  onAnswered: (accepted: boolean) => void;
}) {
  const original = Object.fromEntries(Object.entries(payload.updates).map(([k, v]) => [k, String(v)])) as ProfileDraft;
  const [values, setValues] = useState<ProfileDraft>(original);
  const [editing, setEditing] = useState(false);
  const [state, setState] = useState<"open" | "saving" | "accepted" | "rejected">("open");
  const [error, setError] = useState<string | null>(null);

  async function answer(accept: boolean) {
    setState("saving");
    setError(null);
    const edits = Object.fromEntries(
      Object.entries(values).filter(([k, v]) => v !== original[k as ProfileKey]),
    ) as ProfileDraft;
    try {
      await confirmProfile(payload.proposal_id, accept, accept && Object.keys(edits).length ? edits : undefined);
      setState(accept ? "accepted" : "rejected");
      onAnswered(accept);
    } catch (e) {
      setState("open");
      setError(e instanceof Error ? e.message : "Couldn't save. Try again.");
    }
  }

  const done = state === "accepted" || state === "rejected";

  return (
    <section aria-label="Check these details" className="card max-w-md p-5">
      <h3 className="flex items-center gap-2 font-heading font-semibold">
        <UserRoundCheck className="size-5 text-primary" /> Check these details
      </h3>
      <p className="mt-1 text-sm text-muted-foreground">Nothing is saved until you confirm.</p>
      <dl className="mt-4 flex flex-col gap-3">
        {Object.keys(original).map((k) => {
          const f = field(k);
          const v = values[k as ProfileKey] ?? "";
          const set = (nv: string) => setValues((x) => ({ ...x, [k]: nv }));
          return (
            <div key={k} className="flex flex-col gap-1">
              <dt className="text-xs font-medium text-muted-foreground">{f?.label ?? k}</dt>
              <dd>
                {editing && !done ? (
                  f?.type === "select" ? (
                    <select aria-label={f.label} value={v} onChange={(e) => set(e.target.value)} className="field">
                      <option value="">—</option>
                      {f.options?.map((o) => (
                        <option key={o}>{o}</option>
                      ))}
                    </select>
                  ) : (
                    <input aria-label={f?.label ?? k} type={f?.type ?? "text"} value={v} onChange={(e) => set(e.target.value)} className="field" />
                  )
                ) : (
                  <span className="font-medium">{show(k, v)}</span>
                )}
              </dd>
            </div>
          );
        })}
      </dl>
      {error && <p role="alert" className="mt-3 text-sm text-destructive">{error}</p>}
      {done ? (
        <p className="mt-4 flex items-center gap-1.5 text-sm font-medium text-primary">
          {state === "accepted" ? <><Check className="size-4" /> Saved to your profile</> : <><X className="size-4" /> Not saved</>}
        </p>
      ) : (
        <div className="mt-5 flex flex-wrap gap-2">
          <button onClick={() => answer(true)} disabled={state === "saving"} className="btn-primary h-12 px-5">
            <Check className="size-4" /> Confirm
          </button>
          <button onClick={() => setEditing((e) => !e)} disabled={state === "saving"} className="btn-subtle h-12 px-4">
            <PencilLine className="size-4" /> {editing ? "Done editing" : "Edit"}
          </button>
          <button onClick={() => answer(false)} disabled={state === "saving"} className="btn-ghost h-12 px-4">
            Not right
          </button>
        </div>
      )}
    </section>
  );
}
