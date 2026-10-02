"use client";

import type { AuthError } from "@supabase/supabase-js";
import { useState } from "react";

import { Avatar } from "@/components/avatar/Avatar";
import { Button } from "@/components/ui/button";
import { LANGS, type MsgKey, setLang, t, useLang } from "@/lib/i18n";
import { createClient } from "@/lib/supabase/client";
import { cn } from "@/lib/utils";

const isRateLimit = (e: AuthError) =>
  e.code === "over_email_send_rate_limit" || e.code === "over_request_rate_limit" || e.status === 429;

export function LoginForm({ next, authFailed }: { next: string; authFailed: boolean }) {
  const lang = useLang();
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ key: MsgKey; ok: boolean } | null>(
    authFailed ? { key: "login.auth_failed", ok: false } : null,
  );

  const redirectTo = () =>
    `${window.location.origin}/auth/callback?next=${encodeURIComponent(next)}`;

  const fail = (e: AuthError) =>
    setMsg({ key: isRateLimit(e) ? "login.rate_limited" : "login.error", ok: false });

  async function google() {
    setMsg(null);
    const { error } = await createClient().auth.signInWithOAuth({
      provider: "google",
      options: { redirectTo: redirectTo() },
    });
    if (error) fail(error);
  }

  async function magicLink(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setMsg(null);
    const { error } = await createClient().auth.signInWithOtp({
      email,
      options: { emailRedirectTo: redirectTo() },
    });
    setBusy(false);
    if (error) fail(error);
    else setMsg({ key: "login.link_sent", ok: true });
  }

  return (
    <main lang={lang} className="mx-auto flex w-full max-w-sm flex-1 flex-col justify-center gap-6 px-4 py-12">
      <div role="group" aria-label="Language" className="flex justify-center gap-2">
        {LANGS.map((l) => (
          <button
            key={l.id}
            type="button"
            onClick={() => setLang(l.id)}
            aria-pressed={lang === l.id}
            className={cn(
              "h-12 rounded-full border px-4 text-base focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
              lang === l.id ? "border-primary bg-primary text-primary-foreground" : "border-border bg-card",
            )}
          >
            {l.label}
          </button>
        ))}
      </div>

      <div className="flex flex-col items-center gap-3 text-center">
        <Avatar id="aster" size={96} />
        <h1 className="text-2xl font-bold">{t(lang, "login.title")}</h1>
        <p className="text-muted-foreground">{t(lang, "login.subtitle")}</p>
      </div>

      <Button type="button" variant="outline" className="h-12 text-base" onClick={google}>
        {t(lang, "login.google")}
      </Button>

      <p className="text-center text-sm text-muted-foreground">{t(lang, "login.or")}</p>

      <form onSubmit={magicLink} className="flex flex-col gap-3">
        <label htmlFor="email" className="font-medium">
          {t(lang, "login.email")}
        </label>
        <input
          id="email"
          type="email"
          required
          autoComplete="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          className="h-12 rounded-lg border border-input bg-card px-3 text-base focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
        />
        <Button type="submit" className="h-12 text-base" disabled={busy}>
          {t(lang, busy ? "login.sending" : "login.send_link")}
        </Button>
      </form>

      {msg && (
        <p
          role={msg.ok ? "status" : "alert"}
          className={cn("rounded-lg p-3 text-center", msg.ok ? "bg-accent" : "bg-destructive/10 text-destructive")}
        >
          {t(lang, msg.key)}
        </p>
      )}
    </main>
  );
}
