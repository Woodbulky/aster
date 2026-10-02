"use client";

import { ArrowRight, CheckCircle2, Circle, FolderOpen, Languages, MessageCircle, UserRound } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { Avatar } from "@/components/avatar/Avatar";
import { completion } from "@/components/profile/ProfileForm";
import { useShell } from "@/components/shell/AppShell";
import { useAssistant } from "@/lib/api";
import { GENERAL_DOCS, listGeneralDocs } from "@/lib/general-docs";
import { LANGS } from "@/lib/i18n";
import { cn } from "@/lib/utils";

export default function HomePage() {
  const { user, profile, openSetup } = useShell();
  const assistant = useAssistant();
  const [docCount, setDocCount] = useState<number | null>(null);

  useEffect(() => {
    listGeneralDocs()
      .then((d) => setDocCount(Object.keys(d).length))
      .catch(() => setDocCount(0));
  }, []);

  const pct = completion(profile);
  const first = (profile?.full_name?.trim() || user?.name || "").split(/\s+/)[0];
  const lang = LANGS.find((l) => l.id === assistant.language)?.label ?? "English";

  const journey = [
    { title: "Build your profile", note: `${pct}% complete`, done: pct === 100, action: () => openSetup(0) },
    { title: "Add your general documents", note: docCount === null ? "Checking…" : `${docCount} of ${GENERAL_DOCS.length} saved`, done: docCount === GENERAL_DOCS.length, href: "/documents" },
    { title: "Choose a scholarship", note: `${assistant.assistant_name} researches eligibility and documents with sources`, soon: true },
    { title: "Check your documents for the scheme", note: "Reads them, links every value, flags mismatches", soon: true },
    { title: "Fill the official portal together", note: "Share your screen; get guided field by field", soon: true },
  ];

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-8 px-4 py-8 sm:px-8 sm:py-10">
      <div>
        <span className="eyebrow">A good day to move forward</span>
        <h1 className="mt-2 text-3xl font-bold sm:text-4xl">
          {first ? `Welcome, ${first}.` : "Welcome."}
        </h1>
        <p className="mt-2 text-muted-foreground">Big dreams feel closer when you take them one step at a time.</p>
      </div>

      <div className="grid gap-5 lg:grid-cols-[1fr_320px]">
        <section className="relative overflow-hidden rounded-3xl border border-[#dfe7d3] bg-gradient-to-br from-[#e9f0df] via-[#f2f5ea] to-[#fbf1e6] p-7 sm:p-10">
          <div aria-hidden className="absolute -top-20 -right-20 size-80 rounded-full border border-[#d7e1ca]" />
          <div className="relative flex flex-col items-start gap-6 sm:flex-row sm:items-center sm:justify-between">
            <div className="max-w-md">
              <span className="eyebrow">A little guidance. A lot of possibility.</span>
              <h2 className="mt-3 text-4xl leading-tight font-bold text-primary">
                Big dreams.
                <br />
                Less paperwork.
              </h2>
              <p className="mt-4 text-muted-foreground">
                Ask about scholarships, documents or any form field — by typing or talking, in English, हिंदी or मराठी.
              </p>
              <Link href="/chat" className="btn-primary mt-6">
                <MessageCircle className="size-4" /> Talk to {assistant.assistant_name}
              </Link>
            </div>
            <div className="self-center">
              <Avatar id={assistant.avatar_id} size={170} />
            </div>
          </div>
        </section>

        <div className="grid gap-4 sm:grid-cols-3 lg:grid-cols-1">
          <StatTile icon={<UserRound className="size-5" />} tone="bg-sage" value={`${pct}%`} label="Profile ready" onClick={() => openSetup(0)} />
          <StatTile icon={<FolderOpen className="size-5" />} tone="bg-peach" value={docCount === null ? "–" : `${docCount}/${GENERAL_DOCS.length}`} label="Documents saved" href="/documents" />
          <StatTile icon={<Languages className="size-5" />} tone="bg-lavender" value={lang} label="Reply language" href="/profile#companion" />
        </div>
      </div>

      <section className="card p-6 sm:p-8">
        <div className="flex items-baseline justify-between gap-4">
          <h2 className="text-xl font-bold">Your journey</h2>
          <span className="text-sm text-muted-foreground">Aster guides. You decide and submit.</span>
        </div>
        <ol className="mt-6 flex flex-col">
          {journey.map((j, i) => {
            const body = (
              <>
                <span className={cn("flex size-9 shrink-0 items-center justify-center rounded-full", j.done ? "bg-primary text-primary-foreground" : j.soon ? "bg-muted text-muted-foreground" : "bg-sage text-primary")}>
                  {j.done ? <CheckCircle2 className="size-5" /> : j.soon ? <Circle className="size-4" /> : <span className="font-heading text-sm font-bold">{i + 1}</span>}
                </span>
                <span className="min-w-0 flex-1">
                  <strong className={cn("block font-semibold", j.soon && "text-muted-foreground")}>{j.title}</strong>
                  <small className="block text-sm text-muted-foreground">{j.note}</small>
                </span>
                {j.soon ? (
                  <span className="chip bg-butter text-[#6d5d2f]">Coming soon</span>
                ) : (
                  <ArrowRight className="size-4 text-muted-foreground" />
                )}
              </>
            );
            const cls = "flex w-full items-center gap-4 rounded-2xl px-3 py-4 text-left";
            return (
              <li key={j.title} className="border-b border-border last:border-0">
                {j.href ? (
                  <Link href={j.href} className={cn(cls, "hover:bg-muted")}>{body}</Link>
                ) : j.action ? (
                  <button onClick={j.action} className={cn(cls, "hover:bg-muted")}>{body}</button>
                ) : (
                  <div className={cls}>{body}</div>
                )}
              </li>
            );
          })}
        </ol>
      </section>
    </div>
  );
}

function StatTile({ icon, tone, value, label, href, onClick }: { icon: React.ReactNode; tone: string; value: string; label: string; href?: string; onClick?: () => void }) {
  const body = (
    <>
      <span className={cn("flex size-11 shrink-0 items-center justify-center rounded-xl text-primary", tone)}>{icon}</span>
      <span className="min-w-0 flex-1 text-left">
        <strong className="block font-heading text-2xl font-bold">{value}</strong>
        <small className="block text-sm text-muted-foreground">{label}</small>
      </span>
      <ArrowRight className="size-4 text-muted-foreground" />
    </>
  );
  const cls = "card flex items-center gap-4 p-5 transition-colors hover:bg-muted/50";
  return href ? <Link href={href} className={cls}>{body}</Link> : <button onClick={onClick} className={cls}>{body}</button>;
}
