"use client";

import { Check } from "lucide-react";

import { AVATAR_IDS, AVATARS, Avatar } from "@/components/avatar/Avatar";
import type { AssistantSettings } from "@/lib/api";
import { LANGS, type Lang } from "@/lib/i18n";
import { cn } from "@/lib/utils";

/** Avatar, name and reply language. The name follows the avatar until the user types their own. */
export function CompanionPicker({
  value,
  onChange,
}: {
  value: AssistantSettings;
  onChange: (next: AssistantSettings) => void;
}) {
  const followsAvatar = Object.values(AVATARS).some((a) => a.name === value.assistant_name);
  return (
    <div className="flex flex-col gap-6">
      <fieldset>
        <legend className="mb-3 text-sm font-medium">Choose a face</legend>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {AVATAR_IDS.map((id) => {
            const on = value.avatar_id === id;
            return (
              <button
                key={id}
                type="button"
                aria-pressed={on}
                onClick={() =>
                  onChange({ ...value, avatar_id: id, assistant_name: followsAvatar ? AVATARS[id].name : value.assistant_name })
                }
                className={cn(
                  "relative flex flex-col items-center gap-1 rounded-2xl border-2 p-3 transition-colors focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
                  on ? "border-primary bg-sage" : "border-border bg-card hover:bg-muted",
                )}
              >
                {on && (
                  <span className="absolute top-2 right-2 flex size-5 items-center justify-center rounded-full bg-primary text-primary-foreground">
                    <Check className="size-3" />
                  </span>
                )}
                <Avatar id={id} size={68} />
                <strong className="text-sm">{AVATARS[id].name}</strong>
                <small className="text-xs text-muted-foreground">{AVATARS[id].tagline}</small>
              </button>
            );
          })}
        </div>
      </fieldset>

      <div className="flex flex-col gap-1.5">
        <label htmlFor="assistant-name" className="text-sm font-medium">
          What should we call your companion?
        </label>
        <input
          id="assistant-name"
          maxLength={30}
          value={value.assistant_name}
          onChange={(e) => onChange({ ...value, assistant_name: e.target.value })}
          className="field"
        />
      </div>

      <fieldset>
        <legend className="mb-1 text-sm font-medium">Reply language</legend>
        <p className="mb-3 text-xs text-muted-foreground">You can always speak in any of them — even mixed.</p>
        <div className="grid grid-cols-3 gap-2">
          {LANGS.map((l) => {
            const on = value.language === l.id;
            return (
              <button
                key={l.id}
                type="button"
                lang={l.id}
                aria-pressed={on}
                onClick={() => onChange({ ...value, language: l.id as Lang })}
                className={cn(
                  "flex h-12 items-center justify-center gap-1.5 rounded-xl border text-base font-medium focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
                  on ? "border-primary bg-primary text-primary-foreground" : "border-border bg-card hover:bg-muted",
                )}
              >
                {l.label}
                {on && <Check className="size-4" />}
              </button>
            );
          })}
        </div>
      </fieldset>
    </div>
  );
}

