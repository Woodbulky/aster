"use client";

import { ArrowRight, ArrowUp, FileText, FolderOpen, GraduationCap, Mic, MonitorSmartphone, ShieldCheck, UserRound } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { Avatar } from "@/components/avatar/Avatar";
import { completion } from "@/components/profile/ProfileForm";
import { useShell } from "@/components/shell/AppShell";
import { putAssistant, useAssistant } from "@/lib/api";
import { LANGS, type Lang } from "@/lib/i18n";
import { cn } from "@/lib/utils";

type Msg = { id: number; role: "user" | "assistant"; text: string; lang: Lang };

const PROMPTS = [
  { icon: GraduationCap, text: "Which scholarships can I apply for?", note: "Explore MahaDBT schemes" },
  { icon: FileText, text: "Which documents will I need?", note: "Get organised early" },
  { icon: UserRound, text: "Help me complete my profile", note: "Tell me once, reuse everywhere" },
  { icon: MonitorSmartphone, text: "Guide me through the portal form", note: "Field by field, out loud" },
];

// TODO(M3): replace with the /ws conversation. Until then Aster says plainly that it can't answer yet.
const NOT_CONNECTED: Record<Lang, string> = {
  en: "I can't answer yet — my live chat is being connected. Meanwhile, you can finish your profile and upload your general documents so we're ready to go.",
  hi: "मैं अभी जवाब नहीं दे सकता — मेरी लाइव चैट जोड़ी जा रही है। तब तक आप अपनी प्रोफ़ाइल पूरी करें और ज़रूरी दस्तावेज़ अपलोड करें, ताकि हम तैयार रहें।",
  mr: "मी अजून उत्तर देऊ शकत नाही — माझी लाइव्ह चॅट जोडली जात आहे. तोपर्यंत तुमची प्रोफाइल पूर्ण करा आणि सामान्य कागदपत्रे अपलोड करा, म्हणजे आपण तयार राहू.",
};

const GREETING: Record<Lang, string> = {
  en: "Ask me anything about scholarships, documents or a form field.",
  hi: "छात्रवृत्ति, दस्तावेज़ या किसी भी फ़ॉर्म के बारे में पूछिए।",
  mr: "शिष्यवृत्ती, कागदपत्रे किंवा फॉर्मबद्दल काहीही विचारा.",
};

export default function ChatPage() {
  const { profile } = useShell();
  const assistant = useAssistant();
  const lang = (LANGS.some((l) => l.id === assistant.language) ? assistant.language : "en") as Lang;
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const end = useRef<HTMLDivElement>(null);
  const nextId = useRef(0);

  useEffect(() => {
    end.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages]);

  function send(text: string) {
    const t = text.trim();
    if (!t) return;
    const id = (nextId.current += 2);
    setMessages((m) => [
      ...m,
      { id, role: "user", text: t, lang },
      { id: id + 1, role: "assistant", text: NOT_CONNECTED[lang], lang },
    ]);
    setInput("");
  }

  const pct = completion(profile);

  return (
    <div className="flex h-full">
      <section className="flex min-w-0 flex-1 flex-col">
        {/* Conversation header */}
        <div className="flex flex-wrap items-center gap-3 border-b border-border px-4 py-3 sm:px-8">
          <Avatar id={assistant.avatar_id} size={40} />
          <div className="min-w-0">
            <strong className="block leading-tight">{assistant.assistant_name}</strong>
            <small className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <span className="size-1.5 rounded-full bg-[#d6a05a]" /> Preview · live chat connects soon
            </small>
          </div>
          <div role="group" aria-label="Reply language" className="ml-auto flex rounded-xl border border-border bg-card p-1">
            {LANGS.map((l) => (
              <button
                key={l.id}
                lang={l.id}
                aria-pressed={lang === l.id}
                onClick={() => putAssistant({ ...assistant, language: l.id }).catch(console.error)}
                className={cn(
                  "h-9 rounded-lg px-3 text-sm font-medium transition-colors",
                  lang === l.id ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground",
                )}
              >
                {l.label}
              </button>
            ))}
          </div>
        </div>

        {/* Messages / welcome */}
        <div className="min-h-0 flex-1 overflow-y-auto">
          <div className="mx-auto flex min-h-full max-w-3xl flex-col px-4 py-8 sm:px-8">
            {messages.length === 0 ? (
              <div className="my-auto flex flex-col items-center text-center">
                <div className="relative flex size-56 items-center justify-center">
                  <span aria-hidden className="absolute inset-0 rounded-full border border-[#e1e8d7]" />
                  <span aria-hidden className="absolute inset-6 rounded-full bg-sage/60" />
                  <span aria-hidden className="absolute top-6 left-4 text-xl text-[#9db58a]">✧</span>
                  <span aria-hidden className="absolute right-5 bottom-8 text-base text-[#d3a37c]">✦</span>
                  <div className="relative">
                    <Avatar id={assistant.avatar_id} size={150} />
                  </div>
                </div>
                <h1 className="mt-6 text-3xl font-bold sm:text-4xl">Hi, I&apos;m {assistant.assistant_name}.</h1>
                <p lang={lang} className="mt-3 max-w-md text-lg text-muted-foreground">
                  {GREETING[lang]}
                </p>
                <div className="mt-10 grid w-full gap-3 sm:grid-cols-2">
                  {PROMPTS.map((p) => (
                    <button
                      key={p.text}
                      onClick={() => send(p.text)}
                      className="card group flex items-start gap-4 p-5 text-left transition-colors hover:border-[#cfdcc1] hover:bg-[#f7f9f3]"
                    >
                      <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-sage text-primary">
                        <p.icon className="size-5" />
                      </span>
                      <span className="min-w-0 flex-1">
                        <strong className="block font-semibold">{p.text}</strong>
                        <small className="mt-1 block text-sm text-muted-foreground">{p.note}</small>
                      </span>
                      <ArrowRight className="mt-1 size-4 text-muted-foreground transition-transform group-hover:translate-x-0.5" />
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              <ol role="log" aria-label="Conversation" className="flex flex-col gap-8">
                {messages.map((m) =>
                  m.role === "user" ? (
                    <li key={m.id} lang={m.lang} className="ml-auto max-w-[85%] rounded-3xl rounded-br-lg bg-primary px-5 py-3.5 leading-relaxed text-primary-foreground">
                      {m.text}
                    </li>
                  ) : (
                    <li key={m.id} className="flex max-w-[92%] gap-3">
                      <Avatar id={assistant.avatar_id} size={36} />
                      <div className="min-w-0">
                        <span className="text-sm font-semibold">{assistant.assistant_name}</span>
                        <p lang={m.lang} className="mt-1.5 rounded-3xl rounded-tl-lg border border-border bg-card px-5 py-3.5 leading-relaxed">
                          {m.text}
                        </p>
                        <div className="mt-2 flex flex-wrap gap-2">
                          <Link href="/profile" className="chip bg-sage text-primary hover:bg-[#dfe8d3]">
                            <UserRound className="size-3.5" /> My profile
                          </Link>
                          <Link href="/documents" className="chip bg-peach text-[#7a4a2c] hover:bg-[#f7e0cb]">
                            <FolderOpen className="size-3.5" /> My documents
                          </Link>
                        </div>
                      </div>
                    </li>
                  ),
                )}
              </ol>
            )}
            <div ref={end} />
          </div>
        </div>

        {/* Composer */}
        <div className="border-t border-border bg-background px-4 pt-4 pb-5 sm:px-8">
          <form
            onSubmit={(e) => {
              e.preventDefault();
              send(input);
            }}
            className="mx-auto max-w-3xl rounded-3xl border border-input bg-card p-2 shadow-[0_6px_25px_#283b2d0a] focus-within:border-ring focus-within:ring-2 focus-within:ring-ring/20"
          >
            <textarea
              aria-label={`Message ${assistant.assistant_name}`}
              placeholder={`Message ${assistant.assistant_name}… (English, हिंदी or मराठी)`}
              value={input}
              rows={2}
              maxLength={2000}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                  e.preventDefault();
                  send(input);
                }
              }}
              className="block max-h-48 w-full resize-none bg-transparent px-3 py-2 text-base leading-relaxed outline-none placeholder:text-[#8a9387]"
            />
            <div className="flex items-center justify-between gap-2 px-1">
              <span className="text-xs text-muted-foreground">Enter to send · Shift+Enter for a new line</span>
              <div className="flex items-center gap-2">
                <button type="button" disabled title="Voice arrives in the next update" aria-label="Talk (coming soon)" className="btn-ghost size-11 rounded-full p-0">
                  <Mic className="size-5" />
                </button>
                <button type="submit" disabled={!input.trim()} aria-label="Send" className="btn-primary size-11 rounded-full p-0">
                  <ArrowUp className="size-5" />
                </button>
              </div>
            </div>
          </form>
          <p className="mx-auto mt-3 flex max-w-3xl items-center justify-center gap-1.5 text-center text-xs text-muted-foreground">
            <ShieldCheck className="size-3.5" /> {assistant.assistant_name} guides — you review, decide and submit. Never share passwords or OTPs.
          </p>
        </div>
      </section>

      {/* Context panel (wide screens) */}
      <aside className="hidden w-80 shrink-0 flex-col gap-5 overflow-y-auto border-l border-border bg-sidebar/60 p-6 xl:flex">
        <span className="eyebrow">A little context</span>
        <div className="card p-5">
          <div className="flex items-center justify-between text-sm">
            <span className="font-semibold">Profile ready</span>
            <span className="text-muted-foreground">{pct}%</span>
          </div>
          <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-muted">
            <div className="h-full rounded-full bg-primary" style={{ width: `${pct}%` }} />
          </div>
          <p className="mt-3 text-sm text-muted-foreground">
            {assistant.assistant_name} uses your profile to fill forms faster — and asks before saving anything new.
          </p>
        </div>
        <div className="flex flex-col gap-1">
          <h3 className="mb-1 text-sm font-semibold">Shortcuts</h3>
          {[
            { href: "/profile", icon: UserRound, label: "My profile" },
            { href: "/documents", icon: FolderOpen, label: "My documents" },
          ].map((s) => (
            <Link key={s.href} href={s.href} className="flex h-11 items-center gap-3 rounded-xl px-3 text-sm font-medium hover:bg-sidebar-accent">
              <s.icon className="size-4 text-primary" /> {s.label} <ArrowRight className="ml-auto size-4 text-muted-foreground" />
            </Link>
          ))}
        </div>
        <div className="mt-auto rounded-2xl bg-butter p-5 text-sm leading-relaxed">
          <p className="font-heading font-semibold">No question is too small.</p>
          <p className="text-muted-foreground">Talk the way you&apos;d talk to a friend — mixing languages is fine.</p>
        </div>
      </aside>
    </div>
  );
}
