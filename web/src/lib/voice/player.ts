import { motionValue } from "framer-motion";

import type { Lang } from "@/lib/i18n";

const SYNTH_LANG: Record<Lang, string> = { mr: "mr-IN", hi: "hi-IN", en: "en-IN" };

type Item = { messageId: string; audio?: Promise<AudioBuffer | null>; text?: string; lang?: Lang };

/** Plays Aster's reply sentence by sentence, in arrival order (the server sends in `seq` order).
 * `level` (0..1) follows the output amplitude for the avatar. `stop()` is the barge-in. */
export class Player {
  readonly level = motionValue(0);
  /** Chat mode: replies are read, not played. */
  muted = false;
  private onSpeaking: (speaking: boolean) => void = () => {};
  /** Called when the first sentence of a message starts playing (latency overlay). */
  private onFirstAudio: (messageId: string) => void = () => {};

  setListeners(l: { onSpeaking?: (speaking: boolean) => void; onFirstAudio?: (messageId: string) => void }) {
    this.onSpeaking = l.onSpeaking ?? (() => {});
    this.onFirstAudio = l.onFirstAudio ?? (() => {});
  }

  private ctx: AudioContext | null = null;
  private analyser: AnalyserNode | null = null;
  private source: AudioBufferSourceNode | null = null;
  private queue: Item[] = [];
  private playing = false;
  private stopped = new Set<string>();
  private started = new Set<string>();
  private raf = 0;
  private current: string | null = null;

  /** Must run inside a user gesture once (browser autoplay policy). */
  unlock() {
    if (!this.ctx) {
      this.ctx = new AudioContext();
      this.analyser = this.ctx.createAnalyser();
      this.analyser.fftSize = 512;
      this.analyser.connect(this.ctx.destination);
    }
    void this.ctx.resume();
  }

  get speaking() {
    return this.playing;
  }

  enqueueAudio(messageId: string, data: ArrayBuffer) {
    if (this.muted || this.stopped.has(messageId)) return;
    this.unlock();
    const audio = this.ctx!.decodeAudioData(data).catch(() => null);
    this.push({ messageId, audio });
  }

  enqueueText(messageId: string, text: string, lang: Lang) {
    if (this.muted || this.stopped.has(messageId)) return;
    this.push({ messageId, text, lang });
  }

  /** Barge-in: silence now and drop everything still queued for these messages. */
  stop() {
    for (const it of this.queue) this.stopped.add(it.messageId);
    if (this.current) this.stopped.add(this.current);
    this.queue = [];
    if (this.source) {
      this.source.onended = null;
      try {
        this.source.stop();
      } catch {}
      this.source = null;
    }
    if (typeof speechSynthesis !== "undefined") speechSynthesis.cancel();
    this.setPlaying(false);
  }

  /** Ignore late audio for a message the user interrupted. */
  drop(messageId: string) {
    this.stopped.add(messageId);
  }

  private push(it: Item) {
    this.queue.push(it);
    if (!this.playing) void this.next();
  }

  private async next(): Promise<void> {
    const it = this.queue.shift();
    if (!it) {
      this.current = null;
      return this.setPlaying(false);
    }
    this.setPlaying(true);
    this.current = it.messageId;
    if (!this.started.has(it.messageId)) {
      this.started.add(it.messageId);
      this.onFirstAudio(it.messageId);
    }
    if (it.audio) {
      const buf = await it.audio;
      if (!buf || this.stopped.has(it.messageId)) return this.next();
      const src = this.ctx!.createBufferSource();
      src.buffer = buf;
      src.connect(this.analyser!);
      src.onended = () => {
        if (this.source === src) this.source = null;
        void this.next();
      };
      this.source = src;
      src.start();
      return;
    }
    // tts_unavailable: the browser speaks; text only if it has no voice for the language
    const voices = typeof speechSynthesis !== "undefined" ? speechSynthesis.getVoices() : [];
    // Few browsers ship a Marathi voice; a Hindi one reads Devanagari well enough.
    const wanted = it.lang === "mr" ? (["mr", "hi"] as const) : [it.lang!];
    const voice = wanted.map((l) => voices.find((v) => v.lang === SYNTH_LANG[l]) ?? voices.find((v) => v.lang.startsWith(l))).find(Boolean);
    if (!voice) return this.next();
    const u = new SpeechSynthesisUtterance(it.text);
    u.voice = voice;
    u.lang = voice.lang;
    u.onend = u.onerror = () => void this.next();
    speechSynthesis.speak(u);
  }

  private setPlaying(p: boolean) {
    if (this.playing === p) return;
    this.playing = p;
    this.onSpeaking(p);
    cancelAnimationFrame(this.raf);
    if (!p) return this.level.set(0);
    const data = new Uint8Array(this.analyser?.fftSize ?? 512);
    const tick = () => {
      if (this.analyser) {
        this.analyser.getByteTimeDomainData(data);
        let sum = 0;
        for (const v of data) sum += ((v - 128) / 128) ** 2;
        this.level.set(Math.min(1, Math.sqrt(sum / data.length) * 4));
      } else this.level.set(0.3); // speechSynthesis: no signal to analyse
      this.raf = requestAnimationFrame(tick);
    };
    tick();
  }

  close() {
    this.stop();
    void this.ctx?.close();
    this.ctx = null;
  }
}
