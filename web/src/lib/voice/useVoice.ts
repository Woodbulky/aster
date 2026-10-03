"use client";

import { useEffect, useRef, useState } from "react";

import { Mic } from "@/lib/voice/mic";
import type { Player } from "@/lib/voice/player";

type Opts = {
  player: Player;
  sendAudio: (audio: ArrayBuffer, mime: string) => boolean;
  interrupt: () => void;
};

/** Mic + playback glue: barge-in, avatar listening/speaking, and the client-side latency numbers
 * for the dev overlay (speech end -> first audio playing; VAD speech start -> playback stopped). */
export function useVoice({ player, sendAudio, interrupt }: Opts) {
  const [handsFree, setHandsFree] = useState(false);
  const [pressing, setPressing] = useState(false);
  const [userSpeaking, setUserSpeaking] = useState(false);
  const [aiSpeaking, setAiSpeaking] = useState(false);
  const [micError, setMicError] = useState<string | null>(null);
  const [firstAudioMs, setFirstAudioMs] = useState<number | null>(null);
  const [bargeInMs, setBargeInMs] = useState<number | null>(null);
  const speechEndAt = useRef<number | null>(null);
  const [mic] = useState(() => new Mic());

  useEffect(() => {
    mic.setCallbacks({
      onSpeechStart: () => {
        setUserSpeaking(true);
        if (player.speaking) {
          const t = performance.now();
          interrupt(); // stops playback synchronously, then tells the server
          const ms = Math.round(performance.now() - t);
          setBargeInMs(ms);
          console.info(`[aster-voice] barge-in: playback stopped ${ms} ms after VAD speech start`);
        }
      },
      onMisfire: () => setUserSpeaking(false),
      onUtterance: (audio, mime) => {
        setUserSpeaking(false);
        speechEndAt.current = sendAudio(audio, mime) ? performance.now() : null;
      },
    });
    player.setListeners({
      onSpeaking: setAiSpeaking,
      onFirstAudio: () => {
        if (speechEndAt.current == null) return;
        const ms = Math.round(performance.now() - speechEndAt.current);
        speechEndAt.current = null;
        setFirstAudioMs(ms);
        console.info(`[aster-voice] first audio ${ms} ms after speech end`);
      },
    });
  }, [mic, player, sendAudio, interrupt]);

  useEffect(() => () => void mic.destroy(), [mic]);

  function fail(e: unknown) {
    console.error(e);
    setMicError(e instanceof DOMException && e.name === "NotAllowedError" ? "Microphone permission was denied." : "Couldn't start the microphone.");
  }

  async function toggleHandsFree() {
    player.unlock(); // inside the click: lets audio play later
    setMicError(null);
    try {
      if (handsFree) {
        await mic.stopHandsFree();
        setHandsFree(false);
        setUserSpeaking(false);
      } else {
        await mic.startHandsFree();
        setHandsFree(true);
      }
    } catch (e) {
      fail(e);
    }
  }

  async function pressStart() {
    player.unlock();
    setMicError(null);
    setPressing(true);
    try {
      await mic.pressStart();
    } catch (e) {
      setPressing(false);
      setUserSpeaking(false);
      fail(e);
    }
  }

  function pressEnd() {
    setPressing(false);
    mic.pressEnd();
  }

  return {
    handsFree,
    pressing,
    listening: userSpeaking || pressing,
    aiSpeaking,
    micLevel: mic.level,
    micError,
    firstAudioMs,
    bargeInMs,
    toggleHandsFree,
    pressStart,
    pressEnd,
  };
}
