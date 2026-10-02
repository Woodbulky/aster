import { useSyncExternalStore } from "react";

/** Tiny localStorage store shared across components. Storage may be blocked; everything degrades to null. */
const listeners = new Set<() => void>();
const subscribe = (f: () => void) => (listeners.add(f), () => listeners.delete(f));

export function readLocal(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

export function writeLocal(key: string, value: string) {
  try {
    localStorage.setItem(key, value);
  } catch {}
  listeners.forEach((f) => f());
}

export function removeLocal(...keys: string[]) {
  try {
    keys.forEach((k) => localStorage.removeItem(k));
  } catch {}
  listeners.forEach((f) => f());
}

/** `undefined` until hydrated (server render), then the stored string or null. */
export function useLocal(key: string): string | null | undefined {
  return useSyncExternalStore(subscribe, () => readLocal(key), () => undefined);
}
