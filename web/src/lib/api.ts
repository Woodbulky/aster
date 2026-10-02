import type { Tables } from "@/lib/database.types";
import { readLocal, removeLocal, useLocal, writeLocal } from "@/lib/local";
import { createClient } from "@/lib/supabase/client";

export type AssistantSettings = Pick<
  Tables<"assistant_settings">,
  "avatar_id" | "assistant_name" | "language"
>;

/** Profile keys are exactly the `profiles` columns, so the draft is PUT as-is. */
export type ProfileKey = keyof Omit<
  Tables<"profiles">,
  "id" | "email" | "preferred_language" | "created_at" | "updated_at"
>;
/** Form values are kept as strings; the backend casts numbers/dates. Empty = not provided. */
export type ProfileDraft = Partial<Record<ProfileKey, string>>;

const ASSISTANT_KEY = "aster.assistant";
const PROFILE_KEY = "aster.profile";
const OWNER_KEY = "aster.uid"; // whose data the local cache holds
// TODO(phone backup): empty = discover from public_endpoints row `api`; not needed while Render is live.
export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "";

/** Drop this browser's cached profile/companion (sign-out, or another account signed in). */
export function clearLocalCache() {
  removeLocal(ASSISTANT_KEY, PROFILE_KEY, OWNER_KEY);
}

export async function accessToken(): Promise<string | null> {
  const { data } = await createClient().auth.getSession();
  return data.session?.access_token ?? null;
}

function parse<T>(raw: string | null | undefined): T | null {
  try {
    return raw ? (JSON.parse(raw) as T) : null;
  } catch {
    return null;
  }
}

/** Backend call with the Supabase access token. Throws a readable Error on failure. */
async function api<T>(method: string, path: string, body?: unknown): Promise<T> {
  const token = await accessToken();
  if (!token) throw new Error("You're signed out. Please sign in again.");
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      method,
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new Error("Couldn't reach the Aster server. Saved on this device for now.");
  }
  if (!res.ok) {
    const detail = await res.json().then((j: { detail?: unknown }) => j.detail, () => null);
    throw new Error(typeof detail === "string" ? detail : `Couldn't save (error ${res.status}).`);
  }
  return res.json() as Promise<T>;
}

/** Saves locally first (the UI never waits on a sleeping server), then to the backend. */
export async function putAssistant(settings: AssistantSettings): Promise<void> {
  writeLocal(ASSISTANT_KEY, JSON.stringify(settings));
  await api("PUT", "/api/assistant", settings);
}

export function useAssistant(): AssistantSettings {
  const saved = parse<AssistantSettings>(useLocal(ASSISTANT_KEY));
  return saved ?? { avatar_id: "aster", assistant_name: "Aster", language: "en" };
}

export async function putProfile(profile: ProfileDraft): Promise<void> {
  writeLocal(PROFILE_KEY, JSON.stringify(profile));
  await api("PUT", "/api/profile", profile);
}

/** `undefined` before hydration, `null` when the user has never saved a profile. */
export function useProfile(): ProfileDraft | null | undefined {
  const raw = useLocal(PROFILE_KEY);
  return raw === undefined ? undefined : parse<ProfileDraft>(raw);
}

const NOT_DRAFT = new Set(["id", "email", "preferred_language", "created_at", "updated_at"]);
type Me = { profile: Tables<"profiles"> | null; assistant: Tables<"assistant_settings"> | null };

/** Seeds an empty local cache from the database (new device, cleared storage). Never overwrites
 * local choices: users who saved before the backend existed keep theirs until they save again. */
export async function loadMe(): Promise<void> {
  // The cache is per browser, not per account: never show one user's profile to the next.
  const { data } = await createClient().auth.getUser();
  if (!data.user) return;
  if (readLocal(OWNER_KEY) !== data.user.id) {
    clearLocalCache();
    writeLocal(OWNER_KEY, data.user.id);
  }
  const me = await api<Me>("GET", "/api/me");
  if (me.assistant && !readLocal(ASSISTANT_KEY)) {
    const { avatar_id, assistant_name, language } = me.assistant;
    writeLocal(ASSISTANT_KEY, JSON.stringify({ avatar_id, assistant_name, language }));
  }
  if (me.profile && !readLocal(PROFILE_KEY)) {
    const draft = Object.fromEntries(
      Object.entries(me.profile)
        .filter(([k, v]) => v !== null && !NOT_DRAFT.has(k))
        .map(([k, v]) => [k, String(v)]),
    ) as ProfileDraft;
    if (Object.keys(draft).length) writeLocal(PROFILE_KEY, JSON.stringify(draft));
  }
}

/** Answer a confirm_profile card. Saved values also refresh the local profile cache. */
export async function confirmProfile(
  proposalId: string,
  accept: boolean,
  edits?: ProfileDraft,
): Promise<ProfileDraft> {
  const res = await api<{ saved: Record<string, unknown> }>("POST", "/api/profile/confirm", {
    proposal_id: proposalId,
    accept,
    edits,
  });
  const saved = Object.fromEntries(Object.entries(res.saved).map(([k, v]) => [k, String(v)])) as ProfileDraft;
  if (Object.keys(saved).length) {
    const current = parse<ProfileDraft>(readLocal(PROFILE_KEY)) ?? {};
    writeLocal(PROFILE_KEY, JSON.stringify({ ...current, ...saved }));
  }
  return saved;
}

let opening: Promise<string> | null = null;

/** The user's latest active conversation (read via RLS), or a new one. Memoised so a double
 * effect in dev doesn't create two sessions. */
export function openSession(): Promise<string> {
  opening ??= (async () => {
    const { data } = await createClient()
      .from("form_sessions")
      .select("id")
      .eq("status", "active")
      .order("created_at", { ascending: false })
      .limit(1);
    if (data?.[0]) return data[0].id;
    return (await api<{ id: string }>("POST", "/api/sessions", {})).id;
  })().finally(() => {
    opening = null;
  });
  return opening;
}
