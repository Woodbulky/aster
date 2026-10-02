/** The UI is English; these are the languages the assistant speaks and replies in (assistant_settings.language). */
export const LANGS = [
  { id: "en", label: "English" },
  { id: "hi", label: "हिंदी" },
  { id: "mr", label: "मराठी" },
] as const;
export type Lang = (typeof LANGS)[number]["id"];
