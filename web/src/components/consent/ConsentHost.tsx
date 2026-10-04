"use client";

import { ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";

import { Modal } from "@/components/ui/modal";
import { type ConsentScope, setConsentAsker } from "@/lib/api";

/** What the user agrees to. Changing this text = bump CONSENT_VERSION in backend/app/api/me.py. */
const TEXT: Record<ConsentScope, { title: string; why: string; points: string[] }> = {
  documents: {
    title: "Before Aster reads your documents",
    why: "To fill your form with values you can trace back, Aster reads the documents you upload.",
    points: [
      "Your files are stored privately in your account. Only you can open them.",
      "Text is read by OCR and an AI model on our own GPU worker. If it is down, a hosted AI service reads it instead, and your audit trail records that.",
      "Aadhaar and bank account numbers are masked: only the last 4 digits are kept, and the unmasked image is deleted.",
      "Every value shows which document and line it came from. Nothing is sent to any portal by Aster.",
      "You can delete all your documents and data at any time from My profile.",
    ],
  },
  sensitive_profile: {
    title: "Caste and religion are sensitive",
    why: "Many scholarships (for example on MahaDBT) are only for some categories or castes, so their forms ask for these.",
    points: [
      "They are saved only in your private profile and used only to check and fill your forms.",
      "They are optional. Without them, Aster can't check schemes that depend on them.",
      "Aster doesn't read them aloud and can delete them with the rest of your data at any time.",
    ],
  },
};

type Ask = { scope: ConsentScope; resolve: (granted: boolean) => void };

/** One consent screen for the whole app: `ensureConsent(scope)` (lib/api) opens it. */
export function ConsentHost() {
  const [ask, setAsk] = useState<Ask | null>(null);

  useEffect(() => {
    setConsentAsker((scope) => new Promise((resolve) => setAsk({ scope, resolve })));
    return () => setConsentAsker(null);
  }, []);

  if (!ask) return null;
  const text = TEXT[ask.scope];
  const answer = (granted: boolean) => {
    ask.resolve(granted);
    setAsk(null);
  };
  return (
    <Modal title={text.title} subtitle={text.why} onClose={() => answer(false)} className="max-w-lg">
      <div className="overflow-y-auto px-6 py-5">
        <ul className="flex flex-col gap-3">
          {text.points.map((p) => (
            <li key={p} className="flex gap-3 text-sm leading-relaxed">
              <ShieldCheck aria-hidden className="mt-0.5 size-4 shrink-0 text-primary" />
              {p}
            </li>
          ))}
        </ul>
      </div>
      <footer className="flex flex-wrap justify-end gap-3 border-t border-border px-6 py-4">
        <button type="button" className="btn-subtle" onClick={() => answer(false)}>
          Not now
        </button>
        <button type="button" className="btn-primary" onClick={() => answer(true)} autoFocus>
          I agree
        </button>
      </footer>
    </Modal>
  );
}
