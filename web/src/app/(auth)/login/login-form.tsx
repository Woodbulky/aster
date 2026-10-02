"use client";

import type { AuthError } from "@supabase/supabase-js";
import { ArrowLeft, Mail, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { AsterMark, Avatar } from "@/components/avatar/Avatar";
import { createClient } from "@/lib/supabase/client";
import { cn } from "@/lib/utils";

const MSG = {
  auth_failed: "That sign-in link didn't work. Please request a new one.",
  rate_limited: "Too many emails — try Google sign-in or wait a few minutes.",
  error: "Something went wrong. Please try again.",
  link_sent: "Check your inbox and tap the link to continue. You can close this tab.",
} as const;

const isRateLimit = (e: AuthError) =>
  e.code === "over_email_send_rate_limit" || e.code === "over_request_rate_limit" || e.status === 429;

export function LoginForm({ next, authFailed }: { next: string; authFailed: boolean }) {
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ key: keyof typeof MSG; ok: boolean } | null>(
    authFailed ? { key: "auth_failed", ok: false } : null,
  );

  const redirectTo = () => `${window.location.origin}/auth/callback?next=${encodeURIComponent(next)}`;
  const fail = (e: AuthError) => setMsg({ key: isRateLimit(e) ? "rate_limited" : "error", ok: false });

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
    else setMsg({ key: "link_sent", ok: true });
  }

  return (
    <div className="grid flex-1 lg:grid-cols-2">
      <aside className="relative hidden flex-col justify-between overflow-hidden bg-gradient-to-br from-[#e9f0df] via-[#f4f6ee] to-[#fbefe3] p-12 lg:flex">
        <Link href="/" className="flex items-center gap-2 text-primary">
          <AsterMark size={30} />
          <span className="font-heading text-2xl font-bold tracking-tight">aster.</span>
        </Link>
        <div className="flex flex-col items-start gap-8">
          <Avatar id="aster" size={150} />
          <blockquote className="max-w-md font-heading text-3xl leading-snug font-semibold text-primary">
            “Tell me once. I&apos;ll remember it for every form after this.”
          </blockquote>
          <p className="max-w-md text-muted-foreground">
            Your profile and documents are saved to your account, so the next scholarship takes minutes, not days.
          </p>
        </div>
        <p className="flex items-center gap-2 text-sm text-muted-foreground">
          <ShieldCheck className="size-4" /> Aster never asks for portal passwords or OTPs.
        </p>
      </aside>

      <main className="flex flex-col px-4 py-6 sm:px-8">
        <Link href="/" className="btn-ghost h-10 self-start">
          <ArrowLeft className="size-4" /> Back
        </Link>
        <div className="mx-auto flex w-full max-w-sm flex-1 flex-col justify-center gap-7 py-10">
          <div className="flex flex-col items-center gap-3 text-center">
            <div className="lg:hidden">
              <Avatar id="aster" size={88} />
            </div>
            <h1 className="text-3xl font-bold">Welcome to Aster</h1>
            <p className="text-muted-foreground">Sign up or sign in — it&apos;s the same step.</p>
          </div>

          <button type="button" onClick={google} className="btn-subtle w-full">
            <GoogleIcon /> Continue with Google
          </button>

          <div className="flex items-center gap-3 text-sm text-muted-foreground">
            <span className="h-px flex-1 bg-border" /> or use your email <span className="h-px flex-1 bg-border" />
          </div>

          <form onSubmit={magicLink} className="flex flex-col gap-3">
            <label htmlFor="email" className="text-sm font-medium">
              Email address
            </label>
            <input
              id="email"
              type="email"
              required
              autoComplete="email"
              placeholder="you@example.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="field"
            />
            <button type="submit" className="btn-primary w-full" disabled={busy}>
              <Mail className="size-4" /> {busy ? "Sending…" : "Email me a sign-in link"}
            </button>
          </form>

          {msg && (
            <p
              role={msg.ok ? "status" : "alert"}
              className={cn("rounded-xl p-3 text-center text-sm", msg.ok ? "bg-sage text-primary" : "bg-destructive/10 text-destructive")}
            >
              {MSG[msg.key]}
            </p>
          )}

          <p className="text-center text-xs leading-relaxed text-muted-foreground">
            By continuing you agree that Aster only guides you. You review, decide and submit every form yourself.
          </p>
        </div>
      </main>
    </div>
  );
}

function GoogleIcon() {
  return (
    <svg viewBox="0 0 24 24" className="size-5" aria-hidden="true">
      <path fill="#4285F4" d="M22.5 12.3c0-.8-.1-1.5-.2-2.2H12v4.2h5.9a5 5 0 0 1-2.2 3.3v2.7h3.6c2.1-1.9 3.2-4.8 3.2-8z" />
      <path fill="#34A853" d="M12 23c3 0 5.5-1 7.3-2.7l-3.6-2.7c-1 .7-2.2 1.1-3.7 1.1-2.9 0-5.3-1.9-6.2-4.5H2.1v2.8A11 11 0 0 0 12 23z" />
      <path fill="#FBBC05" d="M5.8 14.2a6.6 6.6 0 0 1 0-4.3V7.1H2.1a11 11 0 0 0 0 9.9z" />
      <path fill="#EA4335" d="M12 5.4c1.6 0 3.1.6 4.2 1.7l3.2-3.2A11 11 0 0 0 2.1 7.1l3.7 2.8C6.7 7.3 9.1 5.4 12 5.4z" />
    </svg>
  );
}
