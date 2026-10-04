"use client";

import { motionValue } from "framer-motion";

// Silero model + worklet and the onnxruntime wasm load from the CDN: a bundled build otherwise
// looks for them at "/". Keep the versions in step with package.json.
const VAD_ASSETS = "https://cdn.jsdelivr.net/npm/@ricky0123/vad-web@0.0.31/dist/";
const ORT_ASSETS = "https://cdn.jsdelivr.net/npm/onnxruntime-web@1.30.0/dist/";

let preloaded = false;

/** Warms the browser cache with what hands-free needs (~15 MB, mostly the onnxruntime wasm), so the
 * first mic tap starts at once instead of after a ~5 s download. Skipped on data-saver. */
export function preloadVad() {
  const conn = (navigator as Navigator & { connection?: { saveData?: boolean } }).connection;
  if (preloaded || conn?.saveData) return;
  preloaded = true;
  void import("@ricky0123/vad-web").catch(() => {});
  // The files MicVAD fetches (vad-web uses onnxruntime-web/wasm: the plain simd-threaded build).
  for (const url of [
    `${VAD_ASSETS}silero_vad_v5.onnx`,
    `${VAD_ASSETS}vad.worklet.bundle.min.js`,
    `${ORT_ASSETS}ort-wasm-simd-threaded.mjs`,
    `${ORT_ASSETS}ort-wasm-simd-threaded.wasm`,
  ])
    fetch(url, { priority: "low" } as RequestInit).catch(() => {});
}

const AUDIO: MediaTrackConstraints = { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 };

export type MicCallbacks = {
  /** The user started talking (VAD) or pressed push-to-talk: the barge-in moment. */
  onSpeechStart: () => void;
  /** VAD heard a blip too short to be speech. */
  onMisfire: () => void;
  onUtterance: (audio: ArrayBuffer, mime: string) => void;
};

/** Hands-free (Silero VAD in the browser) or push-to-talk (MediaRecorder). Audio stays in memory
 * and goes only to our backend over the session socket. */
export class Mic {
  readonly level = motionValue(0); // mic input level for the avatar's listening ring
  private vad: { start(): Promise<void>; pause(): Promise<void>; destroy(): Promise<void> } | null = null;
  private rec: MediaRecorder | null = null;
  private recStream: MediaStream | null = null;

  private cb: MicCallbacks = { onSpeechStart: () => {}, onMisfire: () => {}, onUtterance: () => {} };

  setCallbacks(cb: MicCallbacks) {
    this.cb = cb;
  }

  async startHandsFree() {
    if (this.vad) return this.vad.start();
    const { MicVAD, utils } = await import("@ricky0123/vad-web");
    this.vad = await MicVAD.new({
      model: "v5",
      baseAssetPath: VAD_ASSETS,
      onnxWASMBasePath: ORT_ASSETS,
      getStream: () => navigator.mediaDevices.getUserMedia({ audio: AUDIO }),
      redemptionMs: 400, // end-of-speech tail; counts against the 3 s first-audio budget
      minSpeechMs: 250,
      onSpeechStart: () => this.cb.onSpeechStart(),
      onVADMisfire: () => this.cb.onMisfire(),
      onSpeechEnd: (audio: Float32Array) => {
        this.level.set(0);
        this.cb.onUtterance(utils.encodeWAV(audio), "audio/wav");
      },
      onFrameProcessed: (_p, frame: Float32Array) => {
        let sum = 0;
        for (const v of frame) sum += v * v;
        this.level.set(Math.min(1, Math.sqrt(sum / frame.length) * 6));
      },
    });
    await this.vad.start();
  }

  async stopHandsFree() {
    await this.vad?.destroy(); // releases the mic (the browser's recording dot goes away)
    this.vad = null;
    this.level.set(0);
  }

  async pressStart() {
    if (this.rec) return;
    this.cb.onSpeechStart();
    this.recStream = await navigator.mediaDevices.getUserMedia({ audio: AUDIO });
    const mime = MediaRecorder.isTypeSupported("audio/webm;codecs=opus") ? "audio/webm;codecs=opus" : "";
    const rec = new MediaRecorder(this.recStream, mime ? { mimeType: mime } : undefined);
    const chunks: Blob[] = [];
    rec.ondataavailable = (e) => chunks.push(e.data);
    rec.onstop = async () => {
      this.recStream?.getTracks().forEach((t) => t.stop());
      this.recStream = null;
      const blob = new Blob(chunks, { type: rec.mimeType });
      if (blob.size > 2000) this.cb.onUtterance(await blob.arrayBuffer(), rec.mimeType.split(";")[0] || "audio/webm");
      else this.cb.onMisfire();
    };
    this.rec = rec;
    rec.start();
  }

  pressEnd() {
    this.rec?.stop();
    this.rec = null;
  }

  async destroy() {
    this.pressEnd();
    await this.stopHandsFree();
  }
}
