import type { Tables } from "@/lib/database.types";

export type AssistantSettings = Pick<
  Tables<"assistant_settings">,
  "avatar_id" | "assistant_name" | "language"
>;

/**
 * TODO(M2): replace with `PUT ${NEXT_PUBLIC_API_URL}/api/assistant` (Bearer = Supabase access token).
 * RLS lets clients read their rows but never write them, so until the backend route exists the
 * choice only lives in this browser.
 */
export async function putAssistant(settings: AssistantSettings): Promise<void> {
  try {
    localStorage.setItem("aster.assistant", JSON.stringify(settings));
  } catch {}
}
