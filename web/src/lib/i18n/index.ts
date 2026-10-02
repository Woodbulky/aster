import { useSyncExternalStore } from "react";

import en from "./en.json";
import hi from "./hi.json";
import mr from "./mr.json";

export const LANGS = [
  { id: "mr", label: "मराठी" },
  { id: "hi", label: "हिंदी" },
  { id: "en", label: "English" },
] as const;
export type Lang = (typeof LANGS)[number]["id"];
export type MsgKey = keyof typeof en;

const DICTS: Record<Lang, Record<MsgKey, string>> = { en, hi, mr };
const DEFAULT: Lang = "mr";
const KEY = "aster.lang";

export const t = (lang: Lang, key: MsgKey) => DICTS[lang][key] ?? en[key];

const isLang = (v: unknown): v is Lang => LANGS.some((l) => l.id === v);
const listeners = new Set<() => void>();

function readLang(): Lang {
  try {
    const v = localStorage.getItem(KEY);
    return isLang(v) ? v : DEFAULT;
  } catch {
    return DEFAULT;
  }
}

/** UI language: per-browser convenience; the saved choice lives in assistant_settings. */
export function setLang(lang: Lang) {
  try {
    localStorage.setItem(KEY, lang);
  } catch {}
  listeners.forEach((f) => f());
}

export function useLang(): Lang {
  return useSyncExternalStore(
    (f) => (listeners.add(f), () => listeners.delete(f)),
    readLang,
    () => DEFAULT,
  );
}
