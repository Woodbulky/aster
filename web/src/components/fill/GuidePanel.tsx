"use client";

import type { MotionValue } from "framer-motion";
import { Check, Copy, HandHelping, Hourglass, Lock, Play } from "lucide-react";
import { useState } from "react";

import { Avatar, type AvatarState } from "@/components/avatar/Avatar";
import { cn } from "@/lib/utils";
import type { Guidance } from "@/lib/ws/protocol";

const PAUSE_LABEL: Record<string, string> = {
  login: "Login page — type your username and password yourself.",
  otp: "OTP page — type the OTP yourself. Aster won't look.",
  captcha: "Captcha — type it yourself.",
  payment: "Payment page — do this yourself.",
  submit_confirm: "Final submit — review everything; you submit yourself.",
};

/** Copy from the window the button is in: inside the PiP window the main page's clipboard is not focused. */
export function copyFrom(e: React.MouseEvent, text: string) {
  return ((e.currentTarget.ownerDocument.defaultView ?? window).navigator.clipboard.writeText(text));
}

export function CopyButton({ value, label }: { value: string; label: string }) {
  const [done, setDone] = useState(false);
  return (
    <button
      type="button"
      aria-label={`Copy ${label}`}
      onClick={(e) =>
        copyFrom(e, value).then(
          () => {
            setDone(true);
            window.setTimeout(() => setDone(false), 1500);
          },
          () => setDone(false),
        )
      }
      className="btn-ghost h-9 shrink-0 gap-1.5 rounded-lg px-3 text-sm"
    >
      {done ? <Check className="size-4 text-primary" /> : <Copy className="size-4" />} {done ? "Copied" : "Copy"}
    </button>
  );
}

type Props = {
  name: string;
  avatarId: string;
  avatarState: AvatarState;
  avatarLevel?: MotionValue<number>;
  guidance: Guidance | null;
  paused: string | null;
  privateMode: boolean;
  busy: boolean;
  onHelp: () => void;
  onDone: () => void;
  onResume: () => void;
  compact?: boolean; // the PiP window
  children?: React.ReactNode; // extra controls (mic, private mode)
};

/** Aster's current instruction + the field to fill now, with its value, Copy and source. */
export function GuidePanel(p: Props) {
  const g = p.guidance;
  const t = g?.target ?? null;
  return (
    <section aria-label="Guidance" className={cn("flex flex-col gap-3", p.compact ? "p-3" : "card p-5")}>
      <div className="flex items-start gap-3">
        <Avatar id={p.avatarId} size={p.compact ? 44 : 56} state={p.avatarState} level={p.avatarLevel} />
        <div className="min-w-0 flex-1">
          <strong className="text-sm">{p.name}</strong>
          {p.privateMode ? (
            <p className="mt-1 flex items-center gap-1.5 font-medium text-destructive">
              <Lock className="size-4" /> Private mode — {p.name} is not looking at your screen.
            </p>
          ) : p.paused ? (
            <p className="mt-1 flex items-start gap-1.5 font-medium">
              <Hourglass className="mt-0.5 size-4 shrink-0 text-[#b7791f]" /> {PAUSE_LABEL[p.paused] ?? "Paused."} Guidance resumes on the next page.
            </p>
          ) : (
            <p lang={g?.lang} aria-live="polite" className={cn("mt-1 leading-snug", p.compact ? "text-base" : "text-lg")}>
              {p.busy && !g ? "Looking at your screen…" : (g?.instruction ?? "Share the portal tab and I'll guide you field by field.")}
            </p>
          )}
        </div>
      </div>

      {t && !p.paused && !p.privateMode && (
        <div className="rounded-xl border border-border bg-sage/40 p-3">
          <div className="text-xs text-muted-foreground">{t.label}</div>
          {t.value ? (
            <div className="mt-1 flex items-center gap-2">
              <span className="min-w-0 flex-1 text-lg font-semibold break-words">{t.option_text ?? t.value}</span>
              {!t.option_text && <CopyButton value={t.value} label={t.label} />}
            </div>
          ) : (
            <div className="mt-1 text-sm font-medium">{t.note}</div>
          )}
          {t.source && <div className="mt-1 text-xs text-muted-foreground">from {t.source}</div>}
        </div>
      )}

      <div className="flex flex-wrap gap-2">
        {p.paused && !p.privateMode ? (
          <button type="button" onClick={p.onResume} className="btn-primary h-10 gap-1.5 rounded-xl px-4 text-sm">
            <Play className="size-4" /> I&apos;m past this page
          </button>
        ) : (
          <>
            <button type="button" disabled={p.privateMode || !t} onClick={p.onDone} className="btn-primary h-10 gap-1.5 rounded-xl px-4 text-sm">
              <Check className="size-4" /> Done
            </button>
            <button type="button" disabled={p.privateMode} onClick={p.onHelp} className="btn-ghost h-10 gap-1.5 rounded-xl px-4 text-sm">
              <HandHelping className="size-4" /> Help with this page
            </button>
          </>
        )}
        {p.children}
      </div>
    </section>
  );
}
