"use client";

import { Check, FolderOpen, Save, Trash2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { CompanionPicker } from "@/components/profile/CompanionPicker";
import { completion, type FieldSource, ProfileFields, SECTIONS } from "@/components/profile/ProfileForm";
import { initials, useShell } from "@/components/shell/AppShell";
import { Modal } from "@/components/ui/modal";
import {
  api,
  type AssistantSettings,
  clearLocalCache,
  type ProfileDraft,
  type ProfileKey,
  putAssistant,
  putProfile,
  useAssistant,
} from "@/lib/api";
import { createClient } from "@/lib/supabase/client";

type Sources = Partial<Record<ProfileKey, FieldSource & { value: string }>>;

/** Saved values + where each came from (RLS reads). */
async function loadSources(): Promise<Sources> {
  const sb = createClient();
  const [{ data: profile }, { data: rows }] = await Promise.all([
    sb.from("profiles").select("*").maybeSingle(),
    sb.from("profile_field_sources").select("field_key, source_type, confirmed_at"),
  ]);
  const out: Sources = {};
  for (const r of rows ?? []) {
    const v = (profile as Record<string, unknown> | null)?.[r.field_key];
    if (v !== null && v !== undefined) out[r.field_key as ProfileKey] = { ...r, value: String(v) };
  }
  return out;
}

export default function ProfilePage() {
  const { profile, user } = useShell();
  const assistant = useAssistant();
  if (profile === undefined) return null; // wait for hydration so the editors start from saved values
  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-8 px-4 py-8 sm:px-8 sm:py-10">
      <div>
        <span className="eyebrow">The start of your story</span>
        <h1 className="mt-2 text-3xl font-bold sm:text-4xl">A little about you.</h1>
        <p className="mt-2 text-muted-foreground">Kept together, ready for whatever form comes next.</p>
      </div>
      <div className="grid items-start gap-6 lg:grid-cols-[300px_1fr]">
        <Summary profile={profile ?? {}} email={user?.email ?? ""} fallbackName={user?.name ?? ""} />
        <div className="flex flex-col gap-6">
          <ProfileEditor initial={profile ?? (user?.name ? { full_name: user.name } : {})} />
          <CompanionEditor initial={assistant} />
          <DeleteData />
        </div>
      </div>
    </div>
  );
}

function Summary({ profile, email, fallbackName }: { profile: ProfileDraft; email: string; fallbackName: string }) {
  const name = profile.full_name?.trim() || fallbackName || "Student";
  const pct = completion(profile);
  return (
    <section className="card overflow-hidden lg:sticky lg:top-6">
      <div className="h-20 bg-gradient-to-r from-sage to-peach" />
      <div className="-mt-10 flex flex-col items-center px-6 pb-6 text-center">
        <span className="flex size-20 items-center justify-center rounded-full border-4 border-card bg-[#e3ead8] font-heading text-2xl font-bold text-primary">
          {initials(name)}
        </span>
        <h2 className="mt-3 text-xl font-bold">{name}</h2>
        <p className="text-sm text-muted-foreground">{profile.current_course || email}</p>
        <div className="mt-5 w-full text-left">
          <div className="flex justify-between text-sm">
            <span className="font-medium">Profile ready</span>
            <span className="text-muted-foreground">{pct}%</span>
          </div>
          <div className="mt-2 h-2 overflow-hidden rounded-full bg-muted">
            <div className="h-full rounded-full bg-primary" style={{ width: `${pct}%` }} />
          </div>
        </div>
        <dl className="mt-5 grid w-full gap-3 border-t border-border pt-5 text-left text-sm">
          <div>
            <dt className="eyebrow">Home base</dt>
            <dd className="mt-0.5 font-medium">{[profile.district, profile.domicile_state].filter(Boolean).join(", ") || "—"}</dd>
          </div>
          <div>
            <dt className="eyebrow">Category</dt>
            <dd className="mt-0.5 font-medium">{profile.category || "—"}</dd>
          </div>
        </dl>
        <Link href="/documents" className="btn-subtle mt-5 h-11 w-full text-sm">
          <FolderOpen className="size-4" /> My documents
        </Link>
      </div>
    </section>
  );
}

/** `true` = saved, a string = the save error. */
function SavedNote({ show }: { show: boolean | string }) {
  if (typeof show === "string")
    return (
      <span role="alert" className="text-sm text-destructive">
        {show}
      </span>
    );
  return show ? (
    <span role="status" className="flex items-center gap-1.5 text-sm text-primary">
      <Check className="size-4" /> Saved
    </span>
  ) : null;
}

function ProfileEditor({ initial }: { initial: ProfileDraft }) {
  const [draft, setDraft] = useState(initial);
  const [saved, setSaved] = useState<boolean | string>(false);
  const [sources, setSources] = useState<Sources>({});
  const refresh = useCallback(() => {
    loadSources().then(setSources, () => setSources({}));
  }, []);
  useEffect(refresh, [refresh]);
  return (
    <form
      onSubmit={async (e) => {
        e.preventDefault();
        try {
          await putProfile(draft);
          setSaved(true);
          refresh();
        } catch (err) {
          setSaved((err as Error).message);
        }
      }}
      className="flex flex-col gap-6"
    >
      {SECTIONS.map((s) => (
        <section key={s.id} className="card p-6 sm:p-8">
          <h2 className="text-lg font-bold">{s.title}</h2>
          <p className="mt-1 mb-6 text-sm text-muted-foreground">{s.blurb}</p>
          <ProfileFields
            section={s.id}
            value={draft}
            sources={sources}
            onChange={(d) => {
              setDraft(d);
              setSaved(false);
            }}
          />
        </section>
      ))}
      <div className="sticky bottom-4 z-10 flex items-center justify-end gap-4 rounded-2xl border border-border bg-card/95 p-3 shadow-lg backdrop-blur">
        <SavedNote show={saved} />
        <button type="submit" className="btn-primary">
          <Save className="size-4" /> Save profile
        </button>
      </div>
    </form>
  );
}

function CompanionEditor({ initial }: { initial: AssistantSettings }) {
  const [value, setValue] = useState(initial);
  const [saved, setSaved] = useState<boolean | string>(false);
  return (
    <section id="companion" className="card scroll-mt-6 p-6 sm:p-8">
      <h2 className="text-lg font-bold">Your companion</h2>
      <p className="mt-1 mb-6 text-sm text-muted-foreground">A familiar face and the language it replies in.</p>
      <CompanionPicker
        value={value}
        onChange={(v) => {
          setValue(v);
          setSaved(false);
        }}
      />
      <div className="mt-6 flex items-center justify-end gap-4">
        <SavedNote show={saved} />
        <button
          type="button"
          className="btn-primary"
          onClick={async () => {
            try {
              await putAssistant({ ...value, assistant_name: value.assistant_name.trim() || "Aster" });
              setSaved(true);
            } catch (err) {
              setSaved((err as Error).message);
            }
          }}
        >
          <Save className="size-4" /> Save companion
        </button>
      </div>
    </section>
  );
}

/** Delete my data: every file and row, then the account itself (backend DELETE /api/me). */
function DeleteData() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [typed, setTyped] = useState("");
  const [state, setState] = useState<"idle" | "deleting" | string>("idle");
  async function remove() {
    setState("deleting");
    try {
      await api("DELETE", "/api/me");
    } catch {
      setState("Nothing was deleted. Check your connection and try again.");
      return;
    }
    clearLocalCache();
    await createClient().auth.signOut().catch(() => {}); // the account is already gone
    router.replace("/");
  }
  return (
    <section aria-labelledby="delete-title" className="card border-destructive/30 p-6 sm:p-8">
      <h2 id="delete-title" className="text-lg font-bold">
        Delete my data
      </h2>
      <p className="mt-1 text-sm text-muted-foreground">
        Removes your profile, documents, conversations, applications and audit trail, then your account. This can&apos;t be undone.
      </p>
      <button type="button" onClick={() => setOpen(true)} className="btn-subtle mt-5 text-destructive">
        <Trash2 className="size-4" /> Delete everything
      </button>
      {open && (
        <Modal title="Delete all your data?" subtitle="Your account is deleted too. You can sign up again later." onClose={() => setOpen(false)} className="max-w-md">
          <form
            className="flex flex-col gap-4 px-6 py-5"
            onSubmit={(e) => {
              e.preventDefault();
              if (typed === "DELETE") remove();
            }}
          >
            <label htmlFor="confirm-delete" className="text-sm">
              Type <strong>DELETE</strong> to confirm
            </label>
            <input id="confirm-delete" value={typed} onChange={(e) => setTyped(e.target.value)} className="field" autoComplete="off" />
            {state !== "idle" && state !== "deleting" && (
              <p role="alert" className="text-sm text-destructive">
                {state}
              </p>
            )}
            <div className="flex justify-end gap-3">
              <button type="button" className="btn-subtle" onClick={() => setOpen(false)}>
                Cancel
              </button>
              <button type="submit" disabled={typed !== "DELETE" || state === "deleting"} className="btn-primary bg-destructive disabled:opacity-50">
                {state === "deleting" ? "Deleting…" : "Delete my data"}
              </button>
            </div>
          </form>
        </Modal>
      )}
    </section>
  );
}
