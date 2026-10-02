/** Post-login redirect target: same-origin relative paths only (no open redirects). */
export function safeNext(next: string | null | undefined, fallback = "/onboarding"): string {
  // "//x" and "/\x" are protocol-relative to browsers; reject both, plus control chars.
  if (!next || !next.startsWith("/") || next.startsWith("//") || /[\\\x00-\x1f]/.test(next)) {
    return fallback;
  }
  return next;
}
