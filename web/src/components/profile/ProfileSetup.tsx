"use client";

import { ArrowLeft, ArrowRight, Check } from "lucide-react";
import { useState } from "react";

import { Avatar } from "@/components/avatar/Avatar";
import { CompanionPicker } from "@/components/profile/CompanionPicker";
import { DocVault } from "@/components/profile/DocVault";
import { ProfileFields, SECTIONS } from "@/components/profile/ProfileForm";
import { Modal } from "@/components/ui/modal";
import { type AssistantSettings, type ProfileDraft, putAssistant, putProfile } from "@/lib/api";
import { cn } from "@/lib/utils";

const STEPS = [
  ...SECTIONS.map((s) => ({ id: s.id, title: s.title, blurb: s.blurb })),
  { id: "docs", title: "General documents", blurb: "Needed for nearly every form. Each file saves to your account as soon as you pick it." },
  { id: "companion", title: "Your companion", blurb: "Pick who you'd like to talk to, and the language they reply in." },
] as const;

/** First-run profile pop-up. Every "Continue" saves, so closing half-way loses nothing. */
export function ProfileSetup({
  startAt = 0,
  profile,
  assistant,
  onClose,
}: {
  startAt?: number;
  profile: ProfileDraft;
  assistant: AssistantSettings;
  onClose: () => void;
}) {
  const [step, setStep] = useState(startAt);
  const [draft, setDraft] = useState(profile);
  const [companion, setCompanion] = useState(assistant);
  const current = STEPS[step];
  const last = step === STEPS.length - 1;

  async function next(e: React.FormEvent) {
    e.preventDefault();
    await putProfile(draft);
    if (current.id === "companion") {
      await putAssistant({ ...companion, assistant_name: companion.assistant_name.trim() || "Aster" });
    }
    if (last) onClose();
    else setStep(step + 1);
  }

  return (
    <Modal
      onClose={onClose}
      title={
        step === 0 ? (
          <span className="flex items-center gap-3">
            <Avatar id={companion.avatar_id} size={44} /> Let&apos;s set up your profile
          </span>
        ) : (
          current.title
        )
      }
      subtitle={step === 0 ? "You only do this once — every future form reuses it." : current.blurb}
    >
      <div className="flex gap-1.5 px-6 pt-4" aria-hidden>
        {STEPS.map((s, i) => (
          <span key={s.id} className={cn("h-1.5 flex-1 rounded-full", i <= step ? "bg-primary" : "bg-border")} />
        ))}
      </div>
      <p className="px-6 pt-2 text-xs text-muted-foreground">
        Step {step + 1} of {STEPS.length}
        {step === 0 && <> · {current.title}</>}
      </p>

      <form onSubmit={next} className="flex min-h-0 flex-1 flex-col">
        <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
          {step === 0 && <p className="mb-5 text-sm text-muted-foreground">{current.blurb}</p>}
          {current.id === "docs" ? (
            <DocVault />
          ) : current.id === "companion" ? (
            <CompanionPicker value={companion} onChange={setCompanion} />
          ) : (
            <ProfileFields section={current.id} value={draft} onChange={setDraft} />
          )}
        </div>

        <footer className="flex items-center justify-between gap-3 border-t border-border bg-card px-6 py-4">
          {step > 0 ? (
            <button type="button" onClick={() => setStep(step - 1)} className="btn-ghost">
              <ArrowLeft className="size-4" /> Back
            </button>
          ) : (
            <button type="button" onClick={onClose} className="btn-ghost">
              Later
            </button>
          )}
          <div className="flex items-center gap-2">
            {!last && current.id !== "about" && (
              <button type="button" onClick={() => setStep(step + 1)} className="btn-ghost hidden sm:inline-flex">
                Skip
              </button>
            )}
            <button type="submit" className="btn-primary">
              {last ? (
                <>
                  Finish <Check className="size-4" />
                </>
              ) : (
                <>
                  Save & continue <ArrowRight className="size-4" />
                </>
              )}
            </button>
          </div>
        </footer>
      </form>
    </Modal>
  );
}
