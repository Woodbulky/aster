import type { Tables } from "@/lib/database.types";
import { readLocal, useLocal, writeLocal } from "@/lib/local";
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
// TODO(phone backup): empty = discover from public_endpoints row `api`; not needed while Render is live.
const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "";

function parse<T>(raw: string | null | undefined): T | null {
  try {
    return raw ? (JSON.parse(raw) as T) : null;
  } catch {
    return null;
  }
}

/** Backend call with the Supabase access token. Throws a readable Error on failure. */
async function api<T>(method: string, path: string, body?: unknown): Promise<T> {
  const { data } = await createClient().auth.getSession();
  if (!data.session) throw new Error("You're signed out. Please sign in again.");
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      method,
      headers: { Authorization: `Bearer ${data.session.access_token}`, "Content-Type": "application/json" },
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
