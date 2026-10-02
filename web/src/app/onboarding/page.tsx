"use client";

import { motion } from "framer-motion";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { AVATAR_IDS, AVATARS, Avatar, type AvatarId } from "@/components/avatar/Avatar";
import { Button } from "@/components/ui/button";
import { putAssistant } from "@/lib/api";
import { LANGS, setLang, t, useLang } from "@/lib/i18n";
import { createClient } from "@/lib/supabase/client";
import { cn } from "@/lib/utils";

const choice =
  "rounded-2xl border-2 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none";

export default function OnboardingPage() {
  const router = useRouter();
  const lang = useLang();
  const [avatar, setAvatar] = useState<AvatarId>("aster");
  const [name, setName] = useState<string | null>(null); // null = follow the avatar's name
  const [saved, setSaved] = useState(false);
  const assistantName = name ?? AVATARS[avatar].name;

  async function save(e: React.FormEvent) {
    e.preventDefault();
    await putAssistant({ avatar_id: avatar, assistant_name: assistantName.trim() || "Aster", language: lang });
    setSaved(true);
  }

  async function signOut() {
    await createClient().auth.signOut();
    router.replace("/login");
  }

  return (
    <main lang={lang} className="mx-auto flex w-full max-w-md flex-1 flex-col gap-6 px-4 py-8">
      <h1 className="text-center text-2xl font-bold">{t(lang, "onboarding.title")}</h1>

      <motion.div key={avatar} initial={{ scale: 0.85, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} className="flex justify-center">
        <Avatar id={avatar} size={160} />
      </motion.div>

      <form onSubmit={save} className="flex flex-col gap-6">
        <fieldset>
          <legend className="mb-2 font-medium">{t(lang, "onboarding.avatar")}</legend>
          <div className="grid grid-cols-4 gap-2">
            {AVATAR_IDS.map((id) => (
              <motion.button
                key={id}
                type="button"
                whileHover={{ scale: 1.06 }}
                whileTap={{ scale: 0.95 }}
                onClick={() => setAvatar(id)}
                aria-pressed={avatar === id}
                className={cn(choice, "flex flex-col items-center p-1 text-sm", avatar === id ? "border-primary bg-accent" : "border-transparent bg-card")}
              >
                <Avatar id={id} size={64} />
                {AVATARS[id].name}
              </motion.button>
            ))}
          </div>
        </fieldset>

        <div className="flex flex-col gap-2">
          <label htmlFor="assistant-name" className="font-medium">
            {t(lang, "onboarding.name")}
          </label>
          <input
            id="assistant-name"
            maxLength={30}
            value={assistantName}
            onChange={(e) => setName(e.target.value)}
            className="h-12 rounded-lg border border-input bg-card px-3 text-base focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
          />
        </div>

        <fieldset>
          <legend className="mb-2 font-medium">{t(lang, "onboarding.language")}</legend>
          <div className="grid grid-cols-3 gap-2">
            {LANGS.map((l) => (
              <button
                key={l.id}
                type="button"
                onClick={() => setLang(l.id)}
                aria-pressed={lang === l.id}
                className={cn(choice, "h-12 text-base", lang === l.id ? "border-primary bg-primary text-primary-foreground" : "border-border bg-card")}
              >
                {l.label}
              </button>
            ))}
          </div>
        </fieldset>

        <Button type="submit" className="h-12 text-base">
          {t(lang, "onboarding.save")}
        </Button>
        {saved && (
          <p role="status" className="rounded-lg bg-accent p-3 text-center">
            {t(lang, "onboarding.saved")}
          </p>
        )}
      </form>

      <Button type="button" variant="ghost" className="h-12 self-center" onClick={signOut}>
        {t(lang, "onboarding.sign_out")}
      </Button>
    </main>
  );
}
