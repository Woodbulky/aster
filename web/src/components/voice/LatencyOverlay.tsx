"use client";

import type { TurnMetrics } from "@/lib/ws/protocol";

const fmt = (ms: number | null | undefined) => (ms == null ? "–" : `${(ms / 1000).toFixed(2)} s`);

/** Dev-only voice timings (docs/VOICE.md latency budget: first audio ≤ 3 s after speech end).
 * Shown in `pnpm dev`, or anywhere with `?latency` in the URL. */
export function LatencyOverlay({ server, firstAudioMs, bargeInMs }: { server: TurnMetrics | null; firstAudioMs: number | null; bargeInMs: number | null }) {
  const show = process.env.NODE_ENV !== "production" || (typeof window !== "undefined" && new URLSearchParams(window.location.search).has("latency"));
  if (!show) return null;
  const rows: [string, string][] = [
    ["STT", `${fmt(server?.stt_ms)}${server?.stt_provider ? ` · ${server.stt_provider}` : ""}`],
    ["LLM first token", fmt(server?.llm_first_token_ms)],
    ["First audio (server)", fmt(server?.first_audio_ms)],
    ["First audio (heard)", fmt(firstAudioMs)],
    ["Barge-in stop", bargeInMs == null ? "–" : `${bargeInMs} ms`],
  ];
  return (
    <div aria-label="Voice latency (dev)" className="pointer-events-none fixed right-3 bottom-3 z-50 rounded-xl bg-black/75 px-3 py-2 font-mono text-[11px] leading-5 text-white">
      {rows.map(([k, v]) => (
        <div key={k} className="flex justify-between gap-4">
          <span className="text-white/60">{k}</span>
          <span className={k === "First audio (heard)" && firstAudioMs != null && firstAudioMs > 3000 ? "text-red-300" : ""}>{v}</span>
        </div>
      ))}
    </div>
  );
}
