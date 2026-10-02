# Architecture

```
[Next.js PWA — Vercel]  avatar · chat · voice (VAD) · uploads · screen share (desktop) · Document PiP
      │ Supabase JS (auth, RLS reads, storage uploads)          │ HTTPS + WSS (JWT)
      ▼                                                         ▼
[Supabase cloud]  ◀──── service key ────  [Phone: Termux → proot Ubuntu]  FastAPI backend
 Auth · Postgres · Storage · Realtime        agent orchestrator · speech router · research · verification
 gpu_endpoints / public_endpoints            exposed by Cloudflare Tunnel (named: api.<domain>, or quick + registered)
                                                        │ Bearer GATEWAY_TOKEN
                                                        ▼
                                         [Kaggle 2×T4 gateway — Cloudflare quick tunnel]
                                          GPU0 Ollama qwen3-vl:8b (/v1)   GPU1 IndicConformer (/asr) + EasyOCR (/ocr)
External: Sarvam (STT/TTS), Bhashini (fallback), Tavily (search), hosted OpenAI-compatible LLM (fallback brain)
```

## Responsibilities
| Component | Owns | Never does |
|---|---|---|
| web | UI, auth session, mic + VAD, audio playback, screen capture, uploads straight to Storage, rendering cards | Holds service keys; calls the GPU directly |
| backend | Agent loop, tool execution, provider routing, research, verification, rules, audit writes | Persists screen frames; stores full ID numbers |
| Supabase | Source of truth for users, sessions, messages, documents, fields, contradictions, consents, audit | — |
| GPU gateway | Stateless inference (LLM/VLM, ASR, OCR) | Stores anything; holds user identity |

## Endpoint discovery
- **GPU**: the backend reads `select url from gpu_endpoints where name='kaggle-main' and last_seen > now()-interval '3 minutes'`. The result is cached for 30 s. If there is none, it uses fallbacks.
- **Backend URL for web**: `NEXT_PUBLIC_API_URL` if set (named tunnel). Otherwise the web reads `public_endpoints` row `api` (quick tunnel registered by `ops/phone/quick_tunnel.sh`).

## Fallback chains (implemented in code, each with a timeout)
| Capability | Chain | Timeout |
|---|---|---|
| LLM chat/tools | Kaggle `/v1` → `FALLBACK_LLM_*` (OpenAI-compatible) | first token 8 s |
| Vision (docs/screen) | Kaggle `/v1` (qwen3-vl) → fallback LLM (must be vision-capable) | 20 s |
| STT | Sarvam → Bhashini → Kaggle `/asr` (hi/mr only) | 6 s |
| TTS | Sarvam → Bhashini → client `speechSynthesis` (send text-only event) | 5 s |
| OCR | Kaggle `/ocr` → fallback vision LLM asked for lines (no bbox; mark `bbox=null`) | 30 s |
| Search | Tavily → knowledge pack only | 10 s |

Circuit breaker per provider: 3 consecutive failures → skip for 60 s. `/health` reports each provider's state, and the UI shows a small status dot.

## Data flow: one voice turn
mic → VAD end → WS binary (webm/opus) → STT router → transcript event → agent (LLM stream + tools) → sentence chunks → TTS router → audio events → playback. Barge-in: VAD speech start → client stops audio + sends `interrupt` → server cancels the LLM/TTS tasks.

## Security
- JWT from Supabase is verified on every REST call and on WS `hello`.
- CORS is limited to `ALLOWED_ORIGINS`.
- Storage bucket `documents` is private. Path is `{user_id}/{session_id}/{document_id}.{ext}`. The backend reads with the service key; the web uses signed URLs.
- `GATEWAY_TOKEN` lives only in the backend env and in Kaggle Secrets.
- Audit events are hash-chained per session (DB trigger).
- Rate limit WS messages per user (e.g. 30/min) and uploads (20/session).

## Environments
| Env | web | backend | GPU |
|---|---|---|---|
| dev | `pnpm dev` (localhost:3000) | laptop `uvicorn --reload` | Kaggle or fallback |
| demo | Vercel | phone + named tunnel | Kaggle "Save & Run All" |
