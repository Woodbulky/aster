# Voice

## Client (web)
- Mic via `@ricky0123/vad-web` (Silero v5 VAD in the browser; model, worklet and onnxruntime wasm load from jsdelivr, versions pinned in `lib/voice/mic.ts`). Hands-free: on speech end → WAV from the VAD's 16 kHz Float32 samples → send over WS: JSON header `{"type":"audio_start","mime":"audio/wav","lang_hint":"mr"}` followed by one binary frame, then `{"type":"audio_end"}`.
- Push-to-talk ("hold to talk", pointer or Space/Enter) records webm/opus with MediaRecorder: for noisy rooms and demo safety.
- Barge-in: on VAD speech start while Aster is speaking → stop playback immediately, send `{"type":"interrupt"}`.
- Playback: queue `tts_audio` chunks in order of `seq`. If `tts_unavailable` arrives, speak the text with `speechSynthesis` (pick a voice matching `lang`; fall back to text only).
- Avatar state comes from server `agent_state` events plus the local VAD (`listening` instantly on speech start) and local playback (`speaking`, mouth follows an `AnalyserNode`).
- Dev latency overlay (`components/voice/LatencyOverlay.tsx`; in `pnpm dev` or with `?latency`): server STT / LLM first token / first audio (from `turn_metrics`) and the client-side "heard" time (speech end detected → first sentence playing).

## Server
```python
class Transcript(BaseModel): text: str; lang: str; confidence: float | None; provider: str
class STTProvider(Protocol):
    name: str
    async def transcribe(self, audio: bytes, mime: str, lang_hint: str | None) -> Transcript: ...
class TTSProvider(Protocol):
    name: str
    async def synthesize(self, text: str, lang: str, voice: str | None) -> tuple[bytes, str]: ...  # (audio, mime)
```
- `app/speech/router.py` tries providers in order: STT `sarvam → local_gpu`, TTS `sarvam`. Each try has a timeout plus a circuit breaker (3 failures → 60 s skip). On TTS failure for a sentence → emit `tts_unavailable` with the text. No Bhashini (no credentials; decision 2026-10-03).
- Sarvam STT is called with `language_code=unknown`; the detected language is stored on the user's message. **Replies (text and voice) always follow the reply-language toggle** (`hello.lang`; a switch reconnects). Because old-language history otherwise wins (and Marathi/Hindi share a script), the newest user turn in the LLM request gets a note written in the target language (`i18n reply_in`); it is never stored. After a voice turn, replies to UI events (card taps) are spoken too; typing switches spoken replies off.
- Barge-in / new utterance: the running turn is a task; `interrupt` (or a new utterance) cancels the LLM stream and pending TTS. The interrupted reply is not stored.
- `local_gpu` STT = Kaggle `POST /asr` (multipart `file`, form `lang`; hi/mr only, returns 400 for others).
- Streaming: split the LLM stream into sentences (`.`, `?`, `!`, `।`, newline; min 25 chars, max 220) → TTS each sentence concurrently with an ordered `seq` → send as soon as ready.
- Normalise text for TTS: rupee amounts, dates (DD/MM/YYYY spoken naturally), and masked numbers ("ending in 4417").

## Vendors — FETCH CURRENT DOCS BEFORE IMPLEMENTING
- **Sarvam** (docs.sarvam.ai): auth header `api-subscription-key`. Use their current STT model (supports code-mixed Indic + English, language auto-detect) and current TTS model/voices for mr/hi/en. Put model names in config. Prefer their streaming STT if available and simple; otherwise per-utterance REST is fine.
- Current Sarvam setup (checked 2026-10-03): STT `POST /speech-to-text` (multipart, `saaras:v4`), TTS `POST /text-to-speech` (`bulbul:v3`, mp3, base64 `audios[]`). Model/voice names live in `config.py`/env.
- **Bhashini** (not used): a two-step flow — pipeline config call (with `userID` + `ulcaApiKey`) returns the inference endpoint + key, then a compute call. Add it as another provider in `router.py` if credentials appear.
- Never send audio from other users or other sessions in a request. Log only provider name + latency + error, never audio or transcripts with personal data.

## Latency budget (target: first audio ≤ 3 s after the user stops speaking)
VAD tail 0.3 s · upload 0.2 s · STT 0.6–1.0 s · LLM first sentence 0.8–1.5 s · TTS first chunk 0.4–0.7 s. The backend logs per-stage timings per turn (`turn_metrics`) and the UI dev overlay shows them.
