"use client";

import { ArrowRight, ArrowUp, AudioLines, FileText, FolderOpen, GraduationCap, Loader2, Mic, MicOff, MonitorSmartphone, ShieldCheck, UserRound } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { Avatar } from "@/components/avatar/Avatar";
import { ConfirmProfileCard } from "@/components/cards/ConfirmProfileCard";
import { DocumentChecklistCard } from "@/components/cards/DocumentChecklistCard";
import { FieldReviewCard } from "@/components/cards/FieldReviewCard";
import { FlagCard } from "@/components/cards/FlagCard";
import { ReadinessCard } from "@/components/cards/ReadinessCard";
import { EligibilityCard } from "@/components/cards/EligibilityCard";
import { ResearchSummaryCard } from "@/components/cards/ResearchSummaryCard";
import { SchemeSuggestionsCard } from "@/components/cards/SchemeSuggestionsCard";
import { StartScreenShareCard } from "@/components/cards/StartScreenShareCard";
import { completion } from "@/components/profile/ProfileForm";
import { LatencyOverlay } from "@/components/voice/LatencyOverlay";
import { useShell } from "@/components/shell/AppShell";
import { putAssistant, useAssistant } from "@/lib/api";
import { LANGS, type Lang } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { useVoice } from "@/lib/voice/useVoice";
import { type Status, useSessionSocket } from "@/lib/ws/client";

const PROMPTS = [
  { icon: GraduationCap, text: "Which scholarships can I apply for?", note: "MahaDBT, NSP, LIC or any other" },
  { icon: FileText, text: "Which documents will I need?", note: "Get organised early" },
  { icon: UserRound, text: "Help me complete my profile", note: "Tell me once, reuse everywhere" },
  { icon: MonitorSmartphone, text: "Guide me through the portal form", note: "Field by field, out loud" },
];

const GREETING: Record<Lang, string> = {
  en: "Ask me anything about scholarships, documents or a form field.",
  hi: "छात्रवृत्ति, दस्तावेज़ या किसी भी फ़ॉर्म के बारे में पूछिए।",
  mr: "शिष्यवृत्ती, कागदपत्रे किंवा फॉर्मबद्दल काहीही विचारा.",
};

const PHASE_LABEL: Record<string, string> = {
  onboarding: "Getting to know you",
  choose_form: "Choosing a scholarship",
  research: "Looking up the rules",
  eligibility: "Checking the rules",
  documents: "Collecting documents",
  verification: "Checking your documents",
  ready: "Ready to fill the form",
  form_fill: "Filling the form",
};

const STATUS_LABEL: Record<Exclude<Status, "open">, string> = {
  connecting: "Connecting…",
  offline: "Reconnecting…",
  denied: "Can't open this conversation — sign in again",
};

export default function ChatSessionPage() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const { profile } = useShell();
  const assistant = useAssistant();
  const lang = (LANGS.some((l) => l.id === assistant.language) ? assistant.language : "en") as Lang;
  const { items, phase, agent, status, error, metrics, player, sendText, sendUi, sendAudio, interrupt } = useSessionSocket(sessionId, lang);
  const voice = useVoice({ player, sendAudio, interrupt });
  const [input, setInput] = useState("");
  const end = useRef<HTMLDivElement>(null);
  const nearBottom = useRef(true); // the reader scrolled up: leave them there
  const lastTop = useRef(0);
  const scroller = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const last = items.at(-1);
    const mine = last?.kind === "msg" && last.role === "user";
    if (!nearBottom.current && !mine) return;
    // Streaming tokens and long distances (a reloaded history) jump: a smooth scroll per token
    // jitters, and a long one is cut short when cards lay out. A new item nearby glides.
    const el = scroller.current;
    const far = !!el && el.scrollHeight - el.scrollTop - el.clientHeight > el.clientHeight;
    const streaming = last?.kind === "msg" && last.streaming;
    end.current?.scrollIntoView({ behavior: streaming || far ? "auto" : "smooth", block: "end" });
  }, [items, agent.state, agent.detail]); // the "thinking…" line counts too

  const busy = agent.state === "thinking";
  const canSend = status === "open" && !busy;
  // Local mic/playback beat the server's state: they change the instant the user or Aster talks.
  const avatarState = voice.listening ? "listening" : voice.aiSpeaking ? "speaking" : agent.state;
  const avatarLevel = voice.listening ? voice.micLevel : player.level;

  function send(text: string) {
    const t = text.trim();
    if (!t || !canSend) return;
    sendText(t);
    setInput("");
  }

  const pct = completion(profile);
  const statusText = status === "open" ? (phase && PHASE_LABEL[phase]) || "Online" : STATUS_LABEL[status];

  return (
    <div className="flex h-full">
      <section className="flex min-w-0 flex-1 flex-col">
        {/* Conversation header */}
        <div className="flex flex-wrap items-center gap-3 border-b border-border px-4 py-3 sm:px-8">
          <Avatar id={assistant.avatar_id} size={40} state={avatarState} level={avatarLevel} />
          <div className="min-w-0">
            <strong className="block leading-tight">{assistant.assistant_name}</strong>
            <small role="status" className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <span className={cn("size-1.5 rounded-full", status === "open" ? "bg-primary" : "bg-[#d6a05a]")} /> {statusText}
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
        {/* relative: keeps the cards' sr-only (absolute) inputs inside this scroller, not the page */}
        <div
          ref={scroller}
          onScroll={(e) => {
            // Only scrolling up leaves the bottom: our own smooth scroll passes far-from-bottom
            // positions on its way down.
            const el = e.currentTarget;
            const near = el.scrollHeight - el.scrollTop - el.clientHeight < 120;
            if (near || el.scrollTop < lastTop.current) nearBottom.current = near;
            lastTop.current = el.scrollTop;
          }}
          className="relative min-h-0 flex-1 overflow-y-auto"
        >
          <div className="mx-auto flex min-h-full max-w-3xl flex-col px-4 py-8 sm:px-8">
            {items.length === 0 ? (
              <div className="my-auto flex flex-col items-center text-center">
                <div className="relative flex size-56 items-center justify-center">
                  <span aria-hidden className="absolute inset-0 rounded-full border border-[#e1e8d7]" />
                  <span aria-hidden className="absolute inset-6 rounded-full bg-sage/60" />
                  <span aria-hidden className="absolute top-6 left-4 text-xl text-[#9db58a]">✧</span>
                  <span aria-hidden className="absolute right-5 bottom-8 text-base text-[#d3a37c]">✦</span>
                  <div className="relative">
                    <Avatar id={assistant.avatar_id} size={150} state={avatarState} level={avatarLevel} />
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
                      disabled={!canSend}
                      className="card group flex items-start gap-4 p-5 text-left transition-colors hover:border-[#cfdcc1] hover:bg-[#f7f9f3] disabled:opacity-60"
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
              <>
              <h1 className="sr-only">Conversation with {assistant.assistant_name}</h1>
              <div role="log" aria-label="Conversation" aria-live="polite">
              <ol className="flex flex-col gap-8">
                {items.map((it, i) => {
                  if (it.kind === "card") {
                    const card = it.card;
                    // A flag answered by voice comes back as a new card: show only its latest one.
                    if ("flag_id" in card.payload && items.slice(i + 1).some((x) => x.kind === "card" && "flag_id" in x.card.payload && x.card.payload.flag_id === (card.payload as { flag_id: string }).flag_id)) return null;
                    return (
                    <li key={card.card_id} className="pl-12">
                      {card.kind === "confirm_profile" ? (
                        <ConfirmProfileCard
                          payload={card.payload}
                          onAnswered={(ok) =>
                            sendUi(ok ? "profile_confirmed" : "profile_rejected", { proposal_id: card.payload.proposal_id })
                          }
                        />
                      ) : card.kind === "scheme_suggestions" ? (
                        <SchemeSuggestionsCard
                          payload={card.payload}
                          onPick={(o) => sendUi("form_selected", { portal: o.portal, scheme_key: o.scheme_key })}
                        />
                      ) : card.kind === "eligibility" ? (
                        <EligibilityCard payload={card.payload} onContinue={phase === "eligibility" ? () => sendUi("documents_requested") : undefined} />
                      ) : card.kind === "document_checklist" ? (
                        <DocumentChecklistCard payload={card.payload} />
                      ) : card.kind === "field_review" ? (
                        <FieldReviewCard payload={card.payload} />
                      ) : card.kind === "contradiction" || card.kind === "missing_item" || card.kind === "low_confidence" ? (
                        <FlagCard payload={card.payload} onAnswered={(id) => sendUi("flag_resolved", { flag_id: id })} />
                      ) : card.kind === "readiness" ? (
                        <ReadinessCard payload={card.payload} />
                      ) : card.kind === "start_screen_share" ? (
                        <StartScreenShareCard payload={card.payload} />
                      ) : (
                        <ResearchSummaryCard payload={card.payload} />
                      )}
                    </li>
                    );
                  }
                  return it.role === "user" ? (
                    <li key={it.id} lang={it.lang} className="ml-auto max-w-[85%] rounded-3xl rounded-br-lg bg-primary px-5 py-3.5 leading-relaxed whitespace-pre-wrap text-primary-foreground">
                      {it.text}
                    </li>
                  ) : (
                    <li key={it.id} className="flex max-w-[92%] gap-3">
                      <Avatar id={assistant.avatar_id} size={36} />
                      <div className="min-w-0">
                        <span className="text-sm font-semibold">{assistant.assistant_name}</span>
                        <p lang={it.lang} className="mt-1.5 rounded-3xl rounded-tl-lg border border-border bg-card px-5 py-3.5 leading-relaxed whitespace-pre-wrap">
                          {it.text}
                          {it.streaming && <span aria-hidden className="ml-0.5 inline-block h-4 w-1.5 animate-pulse rounded-sm bg-primary/50 align-middle" />}
                        </p>
                      </div>
                    </li>
                  );
                })}
              </ol>
              </div>
              </>
            )}
            {busy && (
              <p role="status" className="mt-6 flex items-center gap-2 pl-12 text-sm text-muted-foreground">
                <Loader2 className="size-4 animate-spin" /> {agent.detail ?? `${assistant.assistant_name} is thinking…`}
              </p>
            )}
            <div ref={end} />
          </div>
        </div>

        {/* Composer */}
        <div className="border-t border-border bg-background px-4 pt-4 pb-5 sm:px-8">
          {(error || voice.micError) && (
            <p role="alert" className="mx-auto mb-2 max-w-3xl text-sm text-destructive">
              {voice.micError ?? error}
            </p>
          )}
          {status === "denied" && (
            <p role="alert" className="mx-auto mb-2 max-w-3xl text-sm">
              This conversation can&apos;t be opened.{" "}
              <Link href="/login" className="font-semibold text-primary underline">
                Sign in again
              </Link>{" "}
              or{" "}
              <Link href="/sessions" className="font-semibold text-primary underline">
                pick another application
              </Link>
              .
            </p>
          )}
          {status === "offline" && (
            <p role="status" className="mx-auto mb-2 max-w-3xl text-sm text-muted-foreground">
              Can&apos;t reach {assistant.assistant_name} right now. Reconnecting by itself; your conversation is saved.
            </p>
          )}
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
              <span className="text-xs text-muted-foreground" aria-live="polite">
                {voice.handsFree ? (voice.listening ? "Listening…" : "Hands-free on — just talk") : "Enter to send · Shift+Enter for a new line"}
              </span>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  disabled={status !== "open"}
                  aria-label="Hold to talk"
                  title="Hold to talk (for noisy rooms)"
                  onPointerDown={(e) => {
                    e.currentTarget.setPointerCapture(e.pointerId);
                    void voice.pressStart();
                  }}
                  onPointerUp={voice.pressEnd}
                  onPointerCancel={voice.pressEnd}
                  onKeyDown={(e) => {
                    if ((e.key === " " || e.key === "Enter") && !e.repeat) {
                      e.preventDefault();
                      void voice.pressStart();
                    }
                  }}
                  onKeyUp={(e) => {
                    if (e.key === " " || e.key === "Enter") voice.pressEnd();
                  }}
                  className={cn("btn-ghost size-11 touch-none rounded-full p-0 select-none", voice.pressing && "bg-sage text-primary")}
                >
                  <AudioLines className="size-5" />
                </button>
                <button
                  type="button"
                  disabled={status !== "open" && !voice.handsFree}
                  aria-pressed={voice.handsFree}
                  aria-label={voice.handsFree ? "Turn hands-free voice off" : "Turn hands-free voice on"}
                  title={voice.handsFree ? "Hands-free on: tap to turn the mic off" : "Talk hands-free"}
                  onClick={() => void voice.toggleHandsFree()}
                  className={cn("size-11 rounded-full p-0", voice.handsFree ? "btn-primary" : "btn-ghost")}
                >
                  {voice.handsFree ? <Mic className="size-5" /> : <MicOff className="size-5" />}
                </button>
                <button type="submit" disabled={!input.trim() || !canSend} aria-label="Send" className="btn-primary size-11 rounded-full p-0">
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

      <LatencyOverlay server={metrics} firstAudioMs={voice.firstAudioMs} bargeInMs={voice.bargeInMs} />

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
          <h2 className="mb-1 text-sm font-semibold">Shortcuts</h2>
          {[
            { href: "/profile", icon: UserRound, label: "My profile" },
            { href: "/documents", icon: FolderOpen, label: "My documents" },
            { href: `/sessions/${sessionId}`, icon: ShieldCheck, label: "Audit trail" },
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
