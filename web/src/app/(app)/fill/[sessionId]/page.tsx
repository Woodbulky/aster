"use client";

import { ExternalLink, Laptop, Lock, LockOpen, Mic, MicOff, MonitorUp, PictureInPicture2, ShieldCheck, Square } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";
import { createPortal } from "react-dom";

import { Avatar } from "@/components/avatar/Avatar";
import { CopyButton, GuidePanel } from "@/components/fill/GuidePanel";
import { api, useAssistant } from "@/lib/api";
import { LANGS, type Lang } from "@/lib/i18n";
import { CHANGED, CHECK_MS, MIN_GAP_MS, NEW_PAGE, hamming, hashVideo, jpegOf } from "@/lib/screen";
import { cn } from "@/lib/utils";
import { useVoice } from "@/lib/voice/useVoice";
import { useSessionSocket } from "@/lib/ws/client";
import type { FrameReason, ReadinessPayload } from "@/lib/ws/protocol";

declare global {
  interface Window {
    // Document Picture-in-Picture (Chrome 116+; MDN "Using the Document Picture-in-Picture API")
    documentPictureInPicture?: { requestWindow(o?: { width?: number; height?: number }): Promise<Window>; window: Window | null };
  }
}

/** A floating window above the portal tab, with this page's styles copied in (a one-time copy). */
async function openPipWindow(): Promise<Window> {
  const w = await window.documentPictureInPicture!.requestWindow({ width: 380, height: 340 });
  for (const sheet of Array.from(document.styleSheets)) {
    try {
      const style = w.document.createElement("style");
      style.textContent = Array.from(sheet.cssRules, (r) => r.cssText).join("");
      w.document.head.appendChild(style);
    } catch {
      if (!sheet.href) continue; // cross-origin sheet: link it instead
      const link = w.document.createElement("link");
      link.rel = "stylesheet";
      link.href = sheet.href;
      w.document.head.appendChild(link);
    }
  }
  w.document.documentElement.className = document.documentElement.className; // font variables
  w.document.body.className = "bg-background text-foreground";
  return w;
}

const noop = () => () => {};
const IDENTIFIERS = new Set(["aadhaar_last4", "bank_account_last4"]); // typed from the document, never copied

export default function FillPage() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const assistant = useAssistant();
  const lang = (LANGS.some((l) => l.id === assistant.language) ? assistant.language : "en") as Lang;
  const sock = useSessionSocket(sessionId, lang);
  const { phase, agent, status, error, player, guidance, paused, resume, sendUi, sendAudio, sendFrame, interrupt } = sock;

  // Android Chrome has no getDisplayMedia (FORM_FILL.md). Server render assumes support.
  const supported = useSyncExternalStore(noop, () => !!navigator.mediaDevices?.getDisplayMedia, () => true);
  const [stream, setStream] = useState<MediaStream | null>(null);
  const [privateMode, setPrivateMode] = useState(false);
  const [shareError, setShareError] = useState<string | null>(null);
  const [ready, setReady] = useState<ReadinessPayload | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [pip, setPip] = useState<Window | null>(null);
  const [pipError, setPipError] = useState<string | null>(null);
  const video = useRef<HTMLVideoElement>(null);
  const scratch = useRef<HTMLCanvasElement | null>(null);
  const lastSent = useRef<{ hash: string; at: number } | null>(null);
  const pausedAt = useRef<string | null>(null); // hash of the page that paused guidance
  // The interval and the mic callback read these, so they must not be stale closures.
  const privateRef = useRef(false);
  const pausedRef = useRef<string | null>(null);
  privateRef.current = privateMode;
  pausedRef.current = paused;

  useEffect(() => {
    api<ReadinessPayload>("GET", `/api/sessions/${sessionId}/readiness`).then(setReady, (e: Error) => setLoadError(e.message));
  }, [sessionId]);

  /** Send what the shared tab shows now. Nothing is sent in private mode, or while paused unless forced. */
  const capture = useCallback(
    async (reason: FrameReason, force = false) => {
      const v = video.current;
      if (!v || privateRef.current || (pausedRef.current && !force)) return;
      const jpeg = await jpegOf(v);
      scratch.current ??= document.createElement("canvas");
      if (jpeg && !privateRef.current && sendFrame(jpeg, reason)) lastSent.current = { hash: hashVideo(v, scratch.current), at: performance.now() };
    },
    [sendFrame],
  );

  // Each utterance goes with a fresh frame (the backend waits for the transcript, so it arrives in time).
  // A page that changed since the last frame goes as "change": the backend starts reading it at once,
  // while the speech is transcribed; an unchanged page is answered from the reading it already has.
  const sendAudioWithFrame = useCallback(
    (audio: ArrayBuffer, mime: string) => {
      const v = video.current;
      if (stream && v?.videoWidth) {
        scratch.current ??= document.createElement("canvas");
        const last = lastSent.current;
        void capture(last && hamming(hashVideo(v, scratch.current), last.hash) > CHANGED ? "change" : "utterance");
      }
      return sendAudio(audio, mime);
    },
    [stream, capture, sendAudio],
  );
  const voice = useVoice({ player, sendAudio: sendAudioWithFrame, interrupt });

  // Frame policy: check every 1.5 s, send when the screen changed (dHash > 10), at most 1 per 3 s.
  // While paused (login/OTP/submit) nothing is sent; a clearly different page resumes guidance.
  useEffect(() => {
    if (!stream) return;
    const id = window.setInterval(() => {
      const v = video.current;
      if (!v || !v.videoWidth || privateRef.current) return;
      scratch.current ??= document.createElement("canvas");
      const h = hashVideo(v, scratch.current);
      if (pausedRef.current) {
        if (pausedAt.current && hamming(h, pausedAt.current) > NEW_PAGE) {
          resume();
          void capture("change", true);
        }
        return;
      }
      const last = lastSent.current;
      if (!last || (hamming(h, last.hash) > CHANGED && performance.now() - last.at >= MIN_GAP_MS)) void capture("change");
    }, CHECK_MS);
    return () => window.clearInterval(id);
  }, [stream, capture, resume]);

  useEffect(() => {
    pausedAt.current = paused ? (lastSent.current?.hash ?? null) : null;
  }, [paused]);

  // The first look, once the server has moved the session to form_fill.
  const looked = useRef(false);
  useEffect(() => {
    if (stream && phase === "form_fill" && !looked.current) {
      looked.current = true;
      void capture("manual");
    }
  }, [stream, phase, capture]);

  async function startShare() {
    setShareError(null);
    player.unlock();
    try {
      const s = await navigator.mediaDevices.getDisplayMedia({
        video: { displaySurface: "browser" },
        audio: false,
        selfBrowserSurface: "exclude",
        surfaceSwitching: "include",
      } as DisplayMediaStreamOptions);
      s.getVideoTracks()[0]?.addEventListener("ended", () => stopShare(s));
      if (video.current) {
        video.current.srcObject = s;
        await video.current.play();
      }
      looked.current = false;
      lastSent.current = null;
      setStream(s);
      sendUi("screen_share_started");
    } catch (e) {
      if (!(e instanceof DOMException && e.name === "NotAllowedError")) console.error(e);
      setShareError("Screen sharing didn't start. Pick the portal tab and press Share.");
    }
  }

  async function openPip() {
    setPipError(null);
    const sideBySide = "Put this window and the portal side by side.";
    if (!window.documentPictureInPicture) return setPipError(`This browser can't float ${assistant.assistant_name} above the portal. ${sideBySide}`);
    try {
      const w = await openPipWindow();
      w.addEventListener("pagehide", () => setPip(null));
      setPip(w);
    } catch (e) {
      console.error(e);
      setPipError(`Couldn't open the floating window. ${sideBySide}`);
    }
  }

  function stopShare(s: MediaStream | null = stream) {
    window.documentPictureInPicture?.window?.close();
    s?.getTracks().forEach((t) => t.stop());
    if (video.current) video.current.srcObject = null;
    setStream(null);
  }

  useEffect(() => () => stream?.getTracks().forEach((t) => t.stop()), [stream]);

  function togglePrivate() {
    const on = !privateMode;
    privateRef.current = on; // at once: a frame in flight is dropped before it is sent
    setPrivateMode(on);
    if (on) interrupt(); // stop talking about the screen
    else void capture("manual");
  }

  const busy = agent.state === "thinking";
  const avatarState = voice.listening ? "listening" : voice.aiSpeaking ? "speaking" : agent.state;
  const avatarLevel = voice.listening ? voice.micLevel : player.level;
  const notReady = phase !== null && phase !== "ready" && phase !== "form_fill";

  const privateButton = (
    <button
      type="button"
      onClick={togglePrivate}
      aria-pressed={privateMode}
      className={cn(
        "h-11 gap-2 rounded-xl px-5 text-base font-semibold",
        privateMode ? "btn-primary" : "border-2 border-destructive bg-destructive text-white hover:bg-destructive/90",
      )}
    >
      {privateMode ? <LockOpen className="size-5" /> : <Lock className="size-5" />}
      {privateMode ? "Resume guidance" : "Private mode"}
    </button>
  );

  /** The guidance panel: in this page, or in the floating PiP window (same handlers, React portal). */
  const panel = (compact: boolean) => (
    <GuidePanel
      compact={compact}
      name={assistant.assistant_name}
      avatarId={assistant.avatar_id}
      avatarState={avatarState}
      avatarLevel={avatarLevel}
      guidance={guidance}
      paused={paused}
      privateMode={privateMode}
      busy={busy}
      onHelp={() => {
        resume();
        void capture("manual", true);
      }}
      onDone={() => void capture("manual")}
      onResume={() => {
        resume();
        void capture("manual", true);
      }}
    >
      <button
        type="button"
        aria-pressed={voice.handsFree}
        aria-label={voice.handsFree ? "Turn the mic off" : "Talk hands-free"}
        onClick={() => void voice.toggleHandsFree()}
        className={cn("size-10 rounded-xl p-0", voice.handsFree ? "btn-primary" : "btn-ghost")}
      >
        {voice.handsFree ? <Mic className="size-4" /> : <MicOff className="size-4" />}
      </button>
      {compact && privateButton}
    </GuidePanel>
  );

  return (
    <div className="h-full overflow-y-auto">
      <div className="flex flex-wrap items-center gap-3 border-b border-border px-4 py-3 sm:px-8">
        <Avatar id={assistant.avatar_id} size={40} state={avatarState} level={avatarLevel} />
        <div className="min-w-0">
          <strong className="block leading-tight">Guided filling with {assistant.assistant_name}</strong>
          <small role="status" className="text-xs text-muted-foreground">
            {status !== "open" ? "Connecting…" : stream ? (privateMode ? "Private mode — not looking" : paused ? "Paused" : "Watching the shared tab") : "Not sharing"}
          </small>
        </div>
        <div className="ml-auto flex items-center gap-2">{stream && privateButton}</div>
      </div>

      <div className="mx-auto grid max-w-6xl gap-6 px-4 py-6 sm:px-8 lg:grid-cols-[1fr_340px]">
        <div className="flex min-w-0 flex-col gap-4">
          {(error || shareError || voice.micError) && (
            <p role="alert" className="text-sm text-destructive">
              {shareError ?? voice.micError ?? error}
            </p>
          )}
          {!supported ? (
            <section className="card p-5">
              <h2 className="flex items-center gap-2 font-heading font-semibold">
                <Laptop className="size-5 text-primary" /> Open {assistant.assistant_name} on a laptop to fill with {assistant.assistant_name}
              </h2>
              <p className="mt-2 text-sm text-muted-foreground">Screen sharing needs Chrome on a laptop or desktop. Open this same page there:</p>
              <div className="mt-3 flex items-center gap-2 rounded-xl bg-muted p-2 pl-3 text-sm break-all">
                <span className="min-w-0 flex-1">{typeof window === "undefined" ? "" : window.location.href}</span>
                <CopyButton value={typeof window === "undefined" ? "" : window.location.href} label="link" />
              </div>
            </section>
          ) : notReady ? (
            <section className="card p-5">
              <h2 className="font-heading font-semibold">Finish the checks first</h2>
              <p className="mt-2 text-sm text-muted-foreground">Guided filling opens once nothing blocks your form.</p>
              <Link href={`/chat/${sessionId}`} className="btn-primary mt-3 inline-flex h-10 rounded-xl px-4 text-sm">
                Back to the chat
              </Link>
            </section>
          ) : !stream ? (
            <section className="card p-5">
              <h2 className="font-heading text-lg font-semibold">Fill the portal with {assistant.assistant_name}</h2>
              <ol className="mt-3 flex list-decimal flex-col gap-1.5 pl-5 text-sm">
                <li>Open the scholarship portal in another tab and log in yourself.</li>
                <li>Come back here and share that tab. {assistant.assistant_name} only sees that tab.</li>
                <li>{assistant.assistant_name} tells you what to type in each box. You type, check and submit.</li>
              </ol>
              <div className="mt-4 flex flex-wrap gap-2">
                <button type="button" onClick={() => void startShare()} disabled={status !== "open"} className="btn-primary h-11 gap-2 rounded-xl px-5">
                  <MonitorUp className="size-5" /> Share the portal tab
                </button>
                <a href="/mock-portal/login.html" target="_blank" rel="noopener" className="btn-ghost h-11 gap-2 rounded-xl px-4 text-sm">
                  <ExternalLink className="size-4" /> Practice on the demo portal
                </a>
              </div>
            </section>
          ) : (
            <>
              {pip ? (
                <section className="card flex flex-wrap items-center gap-3 p-5 text-sm">
                  <PictureInPicture2 className="size-5 text-primary" /> {assistant.assistant_name} is in the floating window above your portal.
                  <button type="button" onClick={() => pip.close()} className="btn-ghost ml-auto h-9 rounded-lg px-3">
                    Bring back here
                  </button>
                </section>
              ) : (
                panel(false)
              )}
              {pip && createPortal(panel(true), pip.document.body)}
              <div className="flex flex-wrap gap-2">
                <button type="button" onClick={() => stopShare()} className="btn-ghost h-10 gap-1.5 rounded-xl px-4 text-sm">
                  <Square className="size-4" /> Stop sharing
                </button>
                {!pip && (
                  <button type="button" onClick={() => void openPip()} className="btn-ghost h-10 gap-1.5 rounded-xl px-4 text-sm">
                    <PictureInPicture2 className="size-4" /> Float {assistant.assistant_name} above the portal
                  </button>
                )}
              </div>
              {pipError && <p className="text-sm text-muted-foreground">{pipError}</p>}
              {guidance && guidance.fields.length > 0 && !privateMode && !paused && (
                <section aria-label="Fields on this page" className="card p-4 text-sm">
                  <h3 className="mb-2 font-semibold">{guidance.page_title || "This page"}</h3>
                  <ul className="divide-y divide-border">
                    {guidance.fields.map((f, i) => (
                      <li key={`${f.label}-${i}`} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2">
                        <span className="w-48 shrink-0 text-muted-foreground">{f.label}</span>
                        <span className="min-w-0 flex-1 font-medium">{f.value ?? f.note ?? "—"}</span>
                        <span className={cn("chip", f.filled ? "bg-sage text-primary" : "bg-muted text-muted-foreground")}>{f.filled ? "filled" : "to fill"}</span>
                      </li>
                    ))}
                  </ul>
                </section>
              )}
            </>
          )}
          {/* The shared tab, never shown or stored: frames are grabbed from it in memory. */}
          <video ref={video} muted playsInline aria-hidden className="pointer-events-none fixed top-0 left-0 size-px opacity-0" />
          <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <ShieldCheck className="size-3.5" /> {assistant.assistant_name} never reads passwords or OTPs and never submits for you. Frames are looked at once and not saved.
          </p>
        </div>

        <aside aria-label="Values for the form" className="card h-fit p-4 text-sm">
          <h3 className="font-semibold">Your checked values</h3>
          <p className="mt-1 text-xs text-muted-foreground">Copy a value, or type it from your document.</p>
          {loadError && <p className="mt-2 text-destructive">{loadError}</p>}
          <dl className="mt-2 divide-y divide-border">
            {ready?.fields.map((f) => (
              <div key={f.field_key} className="flex items-center gap-2 py-2">
                <div className="min-w-0 flex-1">
                  <dt className="text-xs text-muted-foreground">{f.label}</dt>
                  <dd className="font-medium break-words">{IDENTIFIERS.has(f.field_key) ? `•••• ${f.value} — type it from your document` : f.value}</dd>
                  <dd className="text-xs text-muted-foreground">{f.source}</dd>
                </div>
                {!IDENTIFIERS.has(f.field_key) && <CopyButton value={f.value} label={f.label} />}
              </div>
            ))}
          </dl>
        </aside>
      </div>
    </div>
  );
}
