import type { Tables } from "@/lib/database.types";
import { useLocal, writeLocal } from "@/lib/local";

export type AssistantSettings = Pick<
  Tables<"assistant_settings">,
  "avatar_id" | "assistant_name" | "language"
>;

/** Profile keys are exactly the `profiles` columns, so M2 can PUT this object as-is. */
export type ProfileKey = keyof Omit<
  Tables<"profiles">,
  "id" | "email" | "preferred_language" | "created_at" | "updated_at"
>;
/** Form values are kept as strings; the backend casts numbers/dates. Empty = not provided. */
export type ProfileDraft = Partial<Record<ProfileKey, string>>;

const ASSISTANT_KEY = "aster.assistant";
const PROFILE_KEY = "aster.profile";

function parse<T>(raw: string | null | undefined): T | null {
  try {
    return raw ? (JSON.parse(raw) as T) : null;
  } catch {
    return null;
  }
}

/**
 * TODO(M2): replace with `PUT ${NEXT_PUBLIC_API_URL}/api/assistant` (Bearer = Supabase access token).
 * RLS lets clients read their rows but never write them, so until the backend route exists the
 * choice only lives in this browser.
 */
export async function putAssistant(settings: AssistantSettings): Promise<void> {
  writeLocal(ASSISTANT_KEY, JSON.stringify(settings));
}

export function useAssistant(): AssistantSettings {
  const saved = parse<AssistantSettings>(useLocal(ASSISTANT_KEY));
  return saved ?? { avatar_id: "aster", assistant_name: "Aster", language: "en" };
}

/** TODO(M2): replace with `PUT /api/profile`; same reason as putAssistant. */
export async function putProfile(profile: ProfileDraft): Promise<void> {
  writeLocal(PROFILE_KEY, JSON.stringify(profile));
}

/** `undefined` before hydration, `null` when the user has never saved a profile. */
export function useProfile(): ProfileDraft | null | undefined {
  const raw = useLocal(PROFILE_KEY);
  return raw === undefined ? undefined : parse<ProfileDraft>(raw);
}
