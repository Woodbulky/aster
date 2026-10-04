# Architecture

```
[Next.js PWA — Vercel]  avatar · chat · voice (VAD) · uploads · screen share (desktop) · Document PiP
      │ Supabase JS (auth, RLS reads, storage uploads)          │ HTTPS + WSS (JWT)
      ▼                                                         ▼
[Supabase cloud]  ◀──── service key ────  [Render web service — singapore]  FastAPI backend
 Auth · Postgres · Storage · Realtime        agent orchestrator · speech router · research · verification
 gpu_endpoints / public_endpoints            https://<service>.onrender.com (manual service, auto-deploy on push to main)
                                                        │ Bearer GATEWAY_TOKEN
                                                        ▼
                                         [Kaggle 2×T4 gateway — Cloudflare quick tunnel]
                                          GPU0 Ollama qwen3-vl:8b-instruct (/v1) GPU1 IndicConformer (/asr) + EasyOCR (/ocr)
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
- **Backend URL for web**: `NEXT_PUBLIC_API_URL=https://<service>.onrender.com`. Only for the phone backup with a quick tunnel: leave it empty and the web reads `public_endpoints` row `api` (registered by `ops/phone/quick_tunnel.sh`).
- **Render free plan sleeps after ~15 min idle** (cold start ~1 min, breaks the first WS connect). The web pings `/health` once per page load from the landing page, `/login` and the app shell (`wakeBackend()` in `lib/api.ts`), so the server wakes while the user signs in. For the demo also run a keep-warm pinger hitting `/health` every ~10 min (e.g. cron-job.org / UptimeRobot), or switch to the Starter plan for demo week.

## Fallback chains (implemented in code, each with a timeout)
| Capability | Chain | Timeout |
|---|---|---|
| LLM chat/tools | Kaggle `/v1` → `FALLBACK_LLM_*` (OpenAI-compatible) | first chunk 8 s; 30 s when tools are offered (Ollama sends a tool call only once complete). A 429 waits (≤ 30 s, 2 retries) and does not trip the breaker |
| Vision (docs/screen) | Kaggle `/v1` (qwen3-vl) → fallback LLM (must be vision-capable) | 20 s |
| STT | Sarvam → Kaggle `/asr` (hi/mr only; used even when `LLM_PRIMARY=fallback`) | 6 s |
| TTS | Sarvam → client `speechSynthesis` (`tts_unavailable` text-only event) | 5 s |
| OCR | Kaggle `/ocr` → fallback vision LLM asked for lines (no bbox; mark `bbox=null`) | 30 s |
| Search | Tavily (`include_raw_content: "text"`) → Context.dev `/web/search` (with page Markdown) when Tavily is down or found nothing official → knowledge pack only | 10 s / 25 s |
| Web page text | own `fetch.py` (SSRF guard, 20 s total) → Context.dev `/web/scrape` (real browser, scanned-PDF OCR) on a 403/timeout, < 500 chars, or a scan the GPU OCR couldn't read | 20 s / 25 s |

`BRAIN_PRIMARY` (env, default `fallback`): who answers conversation turns first (`chat_stream(prefer=…)`); document and other sensitive calls keep `LLM_PRIMARY`'s order. `LLM_PRIMARY` (env): `gpu` (default) = Kaggle first, fallback second; `fallback` = skip GPU discovery entirely (dev without spending Kaggle hours). Routing lives in `app/llm/client.py::route()`; `/health` shows `llm: {primary, active}`.

**Sensitive inputs** (document images, screen frames) prefer the GPU. If only the fallback is available they still go to it, but `route(sensitive=True)` returns `audit=True` and the caller MUST write `audit_events(action='llm.sensitive_fallback', payload={provider:'fallback', kind})`. The image/frame itself never goes in the payload (guardrail 7).

Circuit breaker per provider: 3 consecutive failures → skip for 60 s. `/health` reports each provider's state, and the UI shows a small status dot.

## Data flow: one voice turn
mic → VAD end → WS binary (webm/opus) → STT router → transcript event → agent (LLM stream + tools) → sentence chunks → TTS router → audio events → playback. Barge-in: VAD speech start → client stops audio + sends `interrupt` → server cancels the LLM/TTS tasks.

## Security
- JWT from Supabase is verified on every REST call and on WS `hello`.
- CORS is limited to `ALLOWED_ORIGINS`.
- Storage bucket `documents` is private. Path is `{user_id}/{session_id}/{document_id}.{ext}`. The backend reads with the service key; the web uses signed URLs.
- `GATEWAY_TOKEN` lives only in the backend env and in Kaggle Secrets.
- Audit events are hash-chained per (session, user) by a DB trigger; inserts into one chain are serialised (advisory lock, ids taken after it, migrations 0005/0006). `uv run python -m app.audit` recomputes every hash.
- Rate limit WS messages per user (e.g. 30/min) and uploads (20/session).

## Environments
| Env | web | backend | GPU |
|---|---|---|---|
| dev | `pnpm dev` (localhost:3000) | laptop `uvicorn --reload` | Kaggle or fallback |
| demo | Vercel | Render (keep-warm or Starter); backup: phone + tunnel | Kaggle "Save & Run All" |
