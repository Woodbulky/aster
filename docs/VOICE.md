# Voice

## Client (web)
- Mic via `@ricky0123/vad-web` (Silero VAD in the browser). On speech end → encode the utterance (webm/opus via MediaRecorder, or WAV from the VAD's Float32 samples) → send over WS: JSON header `{"type":"audio_start","mime":"audio/webm","lang_hint":"mr"}` followed by one binary frame, then `{"type":"audio_end"}`.
- Push-to-talk button as a fallback (noisy rooms, demo safety).
- Barge-in: on VAD speech start while Aster is speaking → stop playback immediately, send `{"type":"interrupt"}`.
- Playback: queue `tts_audio` chunks in order of `seq`. If `tts_unavailable` arrives, speak the text with `speechSynthesis` (pick a voice matching `lang`; fall back to text only).
- Avatar state comes from server `agent_state` events plus the local VAD (`listening` instantly on speech start).

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
- `SpeechRouter` tries providers in order: STT `sarvam → bhashini → local_gpu`, TTS `sarvam → bhashini`. Each try has a timeout plus a circuit breaker. On total TTS failure → emit `tts_unavailable` with the text.
- `local_gpu` STT = Kaggle `POST /asr` (multipart `file`, form `lang`; hi/mr only, returns 400 for others).
- Streaming: split the LLM stream into sentences (`.`, `?`, `!`, `।`, newline; min 25 chars, max 220) → TTS each sentence concurrently with an ordered `seq` → send as soon as ready.
- Normalise text for TTS: rupee amounts, dates (DD/MM/YYYY spoken naturally), and masked numbers ("ending in 4417").

## Vendors — FETCH CURRENT DOCS BEFORE IMPLEMENTING
- **Sarvam** (docs.sarvam.ai): auth header `api-subscription-key`. Use their current STT model (supports code-mixed Indic + English, language auto-detect) and current TTS model/voices for mr/hi/en. Put model names in config. Prefer their streaming STT if available and simple; otherwise per-utterance REST is fine.
- **Bhashini** (bhashini.gov.in / ULCA docs): a two-step flow — pipeline config call (with `userID` + `ulcaApiKey`) returns the inference endpoint + key for the requested task/language, then a compute call. Cache the config response per (task, lang) for 1 h.
- Never send audio from other users or other sessions in a request. Log only provider name + latency + error, never audio or transcripts with personal data.

## Latency budget (target: first audio ≤ 3 s after the user stops speaking)
VAD tail 0.3 s · upload 0.2 s · STT 0.6–1.0 s · LLM first sentence 0.8–1.5 s · TTS first chunk 0.4–0.7 s. The backend logs per-stage timings per turn (`turn_metrics`) and the UI dev overlay shows them.
