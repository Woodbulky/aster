"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { accessToken, API_URL } from "@/lib/api";
import type { Lang } from "@/lib/i18n";
import { createClient } from "@/lib/supabase/client";
import { Player } from "@/lib/voice/player";
import type { AgentStateName, Card, ClientMsg, ConfirmProfilePayload, FrameReason, Guidance, ServerMsg, TurnMetrics, UiEventName } from "@/lib/ws/protocol";

export type Item =
  | { kind: "msg"; id: string; role: "user" | "assistant"; text: string; lang: Lang; streaming?: boolean }
  | { kind: "card"; card: Card };
export type Status = "connecting" | "open" | "offline" | "denied";

const NO_RETRY = new Set([4400, 4401, 4404]); // bad hello / signed out / not your session

/** Cards worth showing again after a reload (the result of a check, not a question). */
const KEPT_CARDS = ["check_eligibility", "save_research", "request_documents", "get_document_status", "ask_resolution", "resolve_flag", "readiness_summary", "start_form_fill"];

/** History (user + assistant messages, pending confirm cards, eligibility/research cards) via
 * RLS, so a reload shows the conversation so far. */
async function loadHistory(sessionId: string): Promise<Item[]> {
  const sb = createClient();
  const [msgs, props, tools] = await Promise.all([
    sb
      .from("messages")
      .select("id, role, content, lang, created_at")
      .eq("session_id", sessionId)
      .in("role", ["user", "assistant"])
      .order("created_at"),
    sb
      .from("profile_proposals")
      .select("id, updates, created_at")
      .eq("session_id", sessionId)
      .eq("status", "pending")
      .order("created_at"),
    sb
      .from("messages")
      .select("id, tool_payload, created_at")
      .eq("session_id", sessionId)
      .eq("role", "tool")
      .in("tool_name", KEPT_CARDS)
      .order("created_at"),
  ]);
  const rows: { at: string; item: Item }[] = [
    ...(msgs.data ?? []).map((m) => ({
      at: m.created_at,
      item: { kind: "msg", id: m.id, role: m.role as "user" | "assistant", text: m.content ?? "", lang: (m.lang ?? "en") as Lang } as Item,
    })),
    ...(props.data ?? []).map((p) => ({
      at: p.created_at,
      item: {
        kind: "card",
        card: { card_id: p.id, kind: "confirm_profile", payload: { proposal_id: p.id, updates: p.updates as ConfirmProfilePayload["updates"] } },
      } as Item,
    })),
    ...(tools.data ?? []).flatMap((m) => {
      const card = (m.tool_payload as { result?: { card?: Card | null } } | null)?.result?.card;
      return card ? [{ at: m.created_at, item: { kind: "card", card } as Item }] : [];
    }),
  ];
  return rows.sort((a, b) => a.at.localeCompare(b.at)).map((r) => r.item);
}

/** The conversation socket: hello on (re)connect, backoff up to 15 s, streaming merged into items,
 * Aster's voice queued on `player`. */
export function useSessionSocket(sessionId: string, lang: Lang) {
  const [items, setItems] = useState<Item[]>([]);
  const [phase, setPhase] = useState<string | null>(null);
  const [agent, setAgent] = useState<{ state: AgentStateName; detail: string | null }>({ state: "idle", detail: null });
  const [status, setStatus] = useState<Status>("connecting");
  const [error, setError] = useState<string | null>(null);
  const [metrics, setMetrics] = useState<TurnMetrics | null>(null);
  const [guidance, setGuidance] = useState<Guidance | null>(null);
  const [paused, setPaused] = useState<string | null>(null); // pause_guidance reason (login/OTP/submit…)
  const [player] = useState(() => new Player());
  const ws = useRef<WebSocket | null>(null);
  const loaded = useRef(false);
  // The reply language: sent in hello (reconnects) and as set_lang on the open socket (no reconnect).
  const langRef = useRef(lang);

  useEffect(() => {
    let closed = false;
    let historyAsked = false; // per run: a reconnect before the history lands must not load it twice
    let retry = 0;
    let timer: number | undefined;
    let happyTimer: number | undefined;
    let audioHeader: Extract<ServerMsg, { type: "tts_audio" }> | null = null; // the next binary frame

    const upsertAssistant = (id: string, f: (text: string) => string, done: boolean, l?: Lang) =>
      setItems((xs) => {
        const i = xs.findIndex((x) => x.kind === "msg" && x.id === id);
        if (i < 0) return [...xs, { kind: "msg", id, role: "assistant", text: f(""), lang: l ?? langRef.current, streaming: !done }];
        const cur = xs[i] as Extract<Item, { kind: "msg" }>;
        const next = [...xs];
        next[i] = { ...cur, text: f(cur.text), streaming: !done, lang: l ?? cur.lang };
        return next;
      });

    function handle(m: ServerMsg) {
      switch (m.type) {
        case "ready":
          retry = 0;
          setStatus("open");
          setPhase(m.phase);
          setError(null);
          break;
        case "phase":
          setPhase(m.phase);
          break;
        case "agent_state":
          setAgent({ state: m.state, detail: m.detail });
          window.clearTimeout(happyTimer);
          if (m.state === "happy") happyTimer = window.setTimeout(() => setAgent({ state: "idle", detail: null }), 2500);
          break;
        case "assistant_delta":
          upsertAssistant(m.message_id, (t) => t + m.text, false);
          break;
        case "assistant_message":
          upsertAssistant(m.message_id, () => m.text, true, m.lang);
          break;
        case "card": {
          const { type: _type, ...card } = m;
          void _type;
          setItems((xs) => [...xs, { kind: "card", card: card as Card }]);
          break;
        }
        case "transcript":
          setItems((xs) => [...xs, { kind: "msg", id: crypto.randomUUID(), role: "user", text: m.text, lang: m.lang }]);
          setError(null);
          break;
        case "tts_audio":
          audioHeader = m;
          break;
        case "tts_unavailable":
          player.enqueueText(m.message_id, m.text, m.lang);
          break;
        case "turn_metrics": {
          const { type: _type, ...rest } = m;
          void _type;
          setMetrics(rest);
          break;
        }
        case "guidance": {
          const { type: _type, ...g } = m;
          void _type;
          setGuidance(g);
          if (!g.sensitive) setPaused(null);
          break;
        }
        case "pause_guidance":
          setPaused(m.reason);
          break;
        case "error":
          setError(m.message);
          setAgent({ state: "idle", detail: null }); // some error paths end a request without agent_state
          break;
      }
    }

    async function connect() {
      if (!loaded.current && !historyAsked) {
        // Side by side with the socket: what streams in first (the greeting) goes after the history.
        historyAsked = true;
        void loadHistory(sessionId)
          .catch(() => [])
          .then((history) => {
            if (closed) return;
            loaded.current = true;
            setItems((xs) => [...history, ...xs]);
          });
      }
      const token = await accessToken();
      if (closed) return;
      if (!token) return setStatus("denied");
      const sock = new WebSocket(`${API_URL.replace(/^http/, "ws")}/ws/session/${sessionId}`);
      ws.current = sock;
      sock.onopen = () => sock.send(JSON.stringify({ type: "hello", token, lang: langRef.current } satisfies ClientMsg));
      sock.binaryType = "arraybuffer";
      sock.onmessage = (e) => {
        if (typeof e.data !== "string") {
          if (audioHeader) player.enqueueAudio(audioHeader.message_id, e.data as ArrayBuffer);
          audioHeader = null;
          return;
        }
        handle(JSON.parse(e.data) as ServerMsg);
      };
      sock.onclose = (e) => {
        if (ws.current === sock) ws.current = null;
        if (closed) return;
        if (NO_RETRY.has(e.code)) return setStatus("denied");
        setStatus("offline");
        setAgent({ state: "idle", detail: null });
        timer = window.setTimeout(connect, Math.min(1000 * 2 ** retry++, 15000));
      };
    }

    void connect();
    return () => {
      closed = true;
      setStatus("connecting");
      window.clearTimeout(timer);
      window.clearTimeout(happyTimer);
      player.stop();
      ws.current?.close();
      ws.current = null;
    };
  }, [sessionId, player]);

  useEffect(() => {
    if (langRef.current === lang) return;
    langRef.current = lang;
    if (ws.current?.readyState === WebSocket.OPEN) ws.current.send(JSON.stringify({ type: "set_lang", lang } satisfies ClientMsg));
  }, [lang]);

  useEffect(() => () => player.close(), [player]);

  const send = useCallback((msg: ClientMsg) => {
    if (ws.current?.readyState !== WebSocket.OPEN) {
      setError("Reconnecting — try again in a moment.");
      return false;
    }
    ws.current.send(JSON.stringify(msg));
    return true;
  }, []);

  const sendText = useCallback(
    (text: string) => {
      if (!send({ type: "user_text", text })) return;
      setAgent({ state: "thinking", detail: null }); // at once; the server's agent_state follows
      setItems((xs) => [...xs, { kind: "msg", id: crypto.randomUUID(), role: "user", text, lang: langRef.current }]);
    },
    [send],
  );

  const sendUi = useCallback(
    (name: UiEventName, payload: Record<string, unknown> = {}) => {
      const ok = send({ type: "ui_event", name, payload });
      if (ok && name !== "screen_share_started") setAgent({ state: "thinking", detail: null }); // that one runs no turn
      return ok;
    },
    [send],
  );

  /** One utterance: header, ONE binary frame, end (docs/API.md). */
  const sendAudio = useCallback(
    (audio: ArrayBuffer, mime: string) => {
      if (!send({ type: "audio_start", mime, lang_hint: langRef.current })) return false;
      ws.current!.send(audio);
      const ok = send({ type: "audio_end" });
      if (ok) setAgent({ state: "thinking", detail: null });
      return ok;
    },
    [send],
  );

  /** One screen frame: header, then ONE binary JPEG (FORM_FILL.md frame policy is the caller's). */
  const sendFrame = useCallback(
    (jpeg: ArrayBuffer, reason: FrameReason) => {
      if (!send({ type: "screen_frame", frame_id: crypto.randomUUID(), reason })) return false;
      ws.current!.send(jpeg);
      return true;
    },
    [send],
  );

  /** Barge-in: silence Aster now and cancel the turn on the server. */
  const interrupt = useCallback(() => {
    player.stop();
    send({ type: "interrupt" });
  }, [send, player]);

  const resume = useCallback(() => setPaused(null), []);

  return { items, phase, agent, status, error, metrics, player, guidance, paused, resume, sendText, sendUi, sendAudio, sendFrame, interrupt };
}
