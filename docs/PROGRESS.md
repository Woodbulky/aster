# Progress log
<!-- Claude Code appends: date · milestone · what changed · how verified · open issues -->

## 2026-10-02 · M0 Scaffold ✅
**What changed**
- `backend/`: uv project (Python 3.12 via `.python-version`, `requires-python <3.13`), FastAPI `GET /health` → `{status:"ok", version}`, CORS from `ALLOWED_ORIGINS`. `config.py` uses pydantic-settings with every `.env.example` key. All keys are optional and blank values fall back to defaults, so the app boots with no env. `ALLOWED_ORIGINS` is comma-separated and defaults to `http://localhost:3000`. ruff + pytest (5 tests). The test client uses `httpx2` (Starlette deprecated `httpx`).
- `web/`: Next.js 16 App Router, TS strict, Tailwind 4, shadcn/ui (base-nova, uses shadcn's `cn` package). Brand tokens: off-white `#fbf8f3`, navy `#14213d`, teal `#0f766e`, saffron `#f28c28`. Noto Sans + Noto Sans Devanagari. Landing page has a static orb and a "Get started" link to `/login`, which 404s until M1. The `typecheck` script is `next typegen && tsc --noEmit`, so it works on a fresh clone.
- Render: live at https://aster-jj5b.onrender.com as a **manual** Web Service, not a Blueprint (root `backend`, build `pip install uv && uv export … -o requirements.txt && pip install -r requirements.txt`, start `uvicorn app.main:app --host 0.0.0.0 --port $PORT`). `render.yaml` mirrors these settings as a reference only; editing it does not change the live service. SETUP_GUIDE Phase 5b, CLAUDE.md, ARCHITECTURE.md and README.md are updated to match.
- `uv.lock` + `pnpm-lock.yaml` committed.

**How verified**
- `uv run pytest -q` → 5 passed; `ruff check` and `ruff format --check` are clean.
- `curl localhost:8000/health` → `{"status":"ok","version":"0.1.0"}`. CORS echoes `http://localhost:3000` and sends no ACAO header for other origins.
- Simulated Render locally (no-dev deps, near-empty env, blank `GPU_STALE_SECONDS`, `PORT=8123`) → `/health` ok.
- `pnpm lint`, `pnpm typecheck` and `pnpm build` pass. `pnpm dev` shows the landing page (screenshot checked in Chrome).
- `curl https://aster-jj5b.onrender.com/health` → HTTP 200 `{"status":"ok","version":"0.1.0"}`, `x-render-origin-server: uvicorn`, CORS header OK.
- `uv export --frozen --no-dev …` contains runtime packages only.

**Open issues**
- Confirm in the Render build log that Python is **3.12.x**: the pip-based build does not enforce `requires-python`. If it shows 3.14, set the env var `PYTHON_VERSION=3.12.13`.
- Confirm Render Auto-Deploy is **On Commit**. The deviation from the M0 Blueprint spec (manual service) is accepted.
- Free plan sleeps after ~15 min idle. A keep-warm pinger is needed before the demo (see ARCHITECTURE).
- The dev-overlay hydration warning on `<body>` comes from a browser extension attribute, not app code.

## 2026-10-02 · M1 Supabase schema + auth + onboarding UI ✅
**What changed**
- `0001_init` was already applied during setup. `0002_advisor_fixes`: revokes RPC `EXECUTE` on `handle_new_user` and `rls_auto_enable` from anon/authenticated; adds 12 covering indexes for foreign keys. `0003_assistant_defaults`: **drift fix**. The live DB had `assistant_settings` defaults `'sathi'/'Sathi'` (from before the rename), while `0001_init.sql` says `'aster'/'Aster'`. This aligns the defaults and backfilled the one existing default row. No other drift was found: a scan of the public schema's defaults, functions and checks turned up nothing else.
- `web/src/lib/database.types.ts` was generated via MCP. 0003 doesn't change it, because defaults aren't part of the generated types.
- Web: `@supabase/ssr` browser/server clients; `src/proxy.ts` (Next 16 renamed middleware to proxy) refreshes the session and checks it with `getClaims()`, then redirects logged-out users to `/login?next=…`. The public routes are `/`, `/login` and `/auth/*`. `auth/callback` does the PKCE code exchange for both Google and magic link. `safeNext()` only allows relative paths: they must start with `/`, and it rejects `//`, `\` and control characters. `/login` has Google + magic link, a mr/hi/en toggle, and a friendly message for the email rate limit (`over_email_send_rate_limit` / `over_request_rate_limit` / HTTP 429). `/onboarding` has the 4-avatar picker, the assistant name (it follows the avatar until the user edits it) and the language. `components/avatar/Avatar.tsx` is an SVG orb in framer-motion: breathes, blinks every 3–6 s, respects `useReducedMotion`. Avatars: Aster-teal, Mitra-saffron, Tara-indigo, Chintu-green. `lib/i18n` has 3 JSON files and a `t()` helper.
- `pnpm test` (`node --test`) runs `safe-next.test.mjs`.

**How verified**
- Signup trigger: the existing Google user has a `profiles` row and an `assistant_settings` row. A fresh signup simulated inside a transaction that raised an exception (so it rolled back) gave `profiles=1 assistant_settings=1 avatar=aster name=Aster lang=mr`, and 0 test users are left behind.
- curl: `/onboarding`, `/chat/abc?x=1` and `/profile` each return 307 to `/login?next=…`; `/` and `/login` return 200. `/auth/callback?next=//evil.com` without a code returns 307 to `/login?error=auth`. `/login?next=//evil.com` renders with the prop `next="/onboarding"`.
- Chrome: the picker swaps avatars with a pop-in animation. A blink was captured in a frame, and the breathe transform measured scale 1.040, then 1.0006, 1.5 s later. Switching to Marathi relabels the UI. Save stores `{avatar_id, assistant_name, language}` locally.
- Advisors: no RLS errors.
- Backend: pytest 5 passed; ruff check and ruff format clean. Web: `pnpm lint`, `typecheck`, `build` and `test` (2 passed) all pass.

**Open issues**
- **Accepted risk:** `register_gpu` / `register_public_endpoint` stay callable by anon/authenticated (advisor WARN 0028/0029). The Kaggle notebook and the phone script register with the anon key, and both functions check the shared secret in `gpu_secrets`.
- Advisor INFO "RLS enabled, no policy" on `gpu_endpoints` / `gpu_secrets` is intended (service key only). The "Leaked password protection" WARN doesn't apply because there are no password logins (Google + magic link only); it's a dashboard toggle if wanted. The unused-index INFOs are expected with no traffic.
- `putAssistant()` saves to localStorage only. **TODO(M2):** call `PUT /api/assistant`. The DB row keeps its defaults until then.
- `/auth/callback` always lands on `/onboarding`, even for returning users. Skipping onboarding needs `GET /api/me` (M2).
- Avatar states other than `idle` are not built yet; they come with voice.
- In the dev overlay, the `<body>` hydration warning is the same browser-extension attribute as in M0.

## 2026-10-02 · LLM_PRIMARY switch (ahead of M2)
**What changed**
- `config.py`: new `llm_primary: "gpu" | "fallback"` (env `LLM_PRIMARY`, default `gpu`; a blank value falls back to the default, an invalid one fails at boot). It's in `.env.example` and in `render.yaml` (`value: gpu`).
- `app/llm/client.py`:
  - `gpu_url()` returns None in fallback mode without doing any discovery. In gpu mode it only uses `GPU_URL_OVERRIDE` until M2 adds the Supabase discovery and the breaker.
  - `route(sensitive=)` returns `Route(provider, audit)`. `audit=True` means a sensitive input went to the fallback, so the caller has to log it (see ARCHITECTURE "Fallback chains").
- `/health` returns `llm: {primary, active}`, where active is `gpu`, `fallback` or `none`.
- **Secret moved:** the Groq keys had been pasted into the tracked `backend/.env.example`, in the uncommitted diff. They were never committed. They're now in the gitignored `backend/.env`, and the example has a blank value.

**How verified**
- pytest: 12 passed. Routing table, fallback mode skips the GPU even when it's up, sensitive audit flag, env parsing, and the `/health` llm field.
- ruff check and ruff format are clean.
- Local `uvicorn` with `LLM_PRIMARY=fallback` → `{"status":"ok","version":"0.1.0","llm":{"primary":"fallback","active":"fallback"}}`.

**Open issues**
- The audit write itself lands in M2, which adds the Supabase repositories. That's now part of M2's acceptance criteria.
- `FALLBACK_LLM_API_KEY` holds 3 comma-separated keys, but nothing splits or rotates them yet. Decide in M2: rotate on 429, or use the first key only.
- `FALLBACK_LLM_MODEL` is still a placeholder in `backend/.env`.

## 2026-10-02 · UI redesign (reference: `chatgpt/`)
**What changed**
- New look across web: sage/cream palette, Manrope + DM Sans, soft-orb avatars (same ids `aster/mitra/tara/chintu`), `@utility` building blocks in `globals.css`.
- Routes: `/` landing page; `/login` split layout (English); `(app)` group with sidebar shell → `/home`, `/chat`, `/documents`, `/profile`. `/onboarding` removed: avatar/name/language moved into the setup pop-up step 5 and `/profile`. `safeNext` default is now `/home`.
- Profile setup pop-up opens on first visit (until something is saved; "Later" holds for the browser session). Every step saves. Field keys = `profiles` columns.
- General documents upload straight to Storage `documents/<uid>/general/<doc_type>/<ts>.<ext>` under the existing RLS (no file name in the path). Aadhaar and bank passbook deliberately excluded (guardrail 6).
- i18n: UI is English; `lib/i18n` now only lists the reply languages. `en/hi/mr.json` dictionaries deleted. Default reply language `en`.
- Chat is a UI preview: replies with an honest "not connected yet" note in the chosen language. **TODO(M3)** wire `/ws`.

**How verified**
- `pnpm lint`, `typecheck`, `test`, `build` pass. Chrome: landing, pop-up (prefills the Google name), home, chat, documents (Storage list OK), profile render.

**Open issues**
- Profile + companion settings still save to localStorage (**TODO(M2)** `PUT /api/profile`, `PUT /api/assistant`).
- `assistant_settings.language` DB default is still `'mr'`; the UI defaults to `en`. Needs a migration if the DB should match.
- Phone width was not checked in a real viewport (layout is responsive: drawer sidebar under `lg`).


## 2026-10-03 · M2 Backend core ✅
**What changed**
- Deps: `supabase` 2.32, `httpx` 0.28 (both in the fixed stack).
- `app/db/supabase.py`: a service-key client (`get_db`, singleton) plus repos for profile, assistant, sessions, messages and audit. Each one takes the JWT `user_id` and filters by it.
- `app/deps.py`: `current_user` checks the Bearer token with `supabase.auth.get_user` and returns 401 on a missing or bad token.
- `app/llm/client.py`:
  - GPU discovery from `gpu_endpoints` (fresh if `last_seen` < `GPU_STALE_SECONDS`), cached for 30 s. Errors return `None`. `GPU_URL_OVERRIDE` wins. In `LLM_PRIMARY=fallback` no query is made.
  - A `Breaker` per provider (3 failures → 60 s open, then half-open).
  - `chat_stream()`: an OpenAI-compatible SSE stream that handles tools and images (base64 `image_url`). Time to first token is capped at 8 s, or 20 s for vision. A failure before the first token goes to the next provider and also clears the discovery cache. Fallback keys rotate on a 429.
  - Image input requires `sensitive_kind` + `user_id`. When the fallback serves such a call, it writes `audit_events(llm.sensitive_fallback, {provider, kind})` **before** sending (fail-closed).
  - Base64 runs in provider error bodies are redacted before logging (guardrail 7).
- REST: `GET /api/me`, `PUT /api/assistant`, `PUT /api/profile` (user-typed values, source `manual`; `extra=forbid`; Aadhaar last-4 only), `POST /api/sessions`. `/health` gains `providers`.
- `scripts/llm_smoke.py`: streams a Marathi reply and prints the provider and timings.
- Web: `lib/api.ts` calls the backend with the Supabase access token, after a local cache write so the UI never waits on a sleeping Render. `loadMe()` fills an empty cache from `/api/me` and never overwrites earlier local choices. The profile page and the setup pop-up show save errors.
- Env: `SUPABASE_URL` and `FALLBACK_LLM_MODEL=qwen/qwen3.8-27b` (Groq's current vision model per console.groq.com/docs/vision, checked 2026-10-03) set in `backend/.env`. Fixed the duplicated key in `web/.env.local` (`NEXT_PUBLIC_API_URL=NEXT_PUBLIC_API_URL=…`).
- `docs/API.md`: `/health` shape + `PUT /api/profile`.

**How verified**
- pytest: 49 passed. Covers the breaker, discovery (fresh/stale/missing/error/30 s cache/override), fallback mode never querying `gpu_endpoints` (route, stream, `/health`), GPU connect error and slow first token → fallback, 429 key rotation, the sensitive audit having no image content, redaction, JWT 401s on every route, user scoping, and payload validation. ruff check and ruff format are clean. Web: lint, typecheck, test and build pass.
- Live smoke test (Groq): Marathi streamed with `provider=fallback first_token=1.03s`. With a dead tunnel URL as the GPU: fallback at 2.05 s. With an unroutable GPU host: fallback at 5.75 s (both < 8 s).
- Live `/health` (gpu mode, stale row 6 min old): `gpu: down, llm_fallback: up, sarvam: configured, tavily: configured`. The service-key discovery query returns the `kaggle-main` row.
- Live: `/api/me` returns 401 with no token and 401 with a forged JWT (rejected by Supabase Auth). The CORS preflight from `localhost:3000` → ACAO echoed.
- Advisors: unchanged from M1 (accepted items only).
- **GPU (Kaggle running, `qwen3-vl:8b-instruct`):** `/health` → `llm.active: gpu, providers.gpu: up`. The smoke test streamed Marathi with `provider=gpu first_token=1.46s total=6.44s`. Notebook stopped (tunnel dead, row still fresh): Cloudflare 530 → `provider=fallback first_token=1.48s` (user run).
- **Model switch:** plain `qwen3-vl:8b` only thinks over `/v1`. Probed on the live gateway at `max_tokens=300`: `reasoning_effort=none`, `reasoning.effort=none`, `think=false` and `/no_think` all gave content=0. A reply only came at `max_tokens=1500`, after 35 s. Moved to `qwen3-vl:8b-instruct` (same size) in the notebook, config, env examples, CLAUDE.md and docs.
- **Browser click-through (user, :3000 → local backend):** the companion save → `assistant_settings` = `aster / Harsh / en`. The profile save → `PUT /api/profile 200` → `profiles` filled (taluka updated), 14 `profile_field_sources` rows, all `manual`.

**Open issues**
- Qwen sometimes slips a Chinese character into Marathi output (seen once: "च核 करा"). M3: say so in the system prompt and/or strip CJK in post-processing before the reply is spoken or shown.
- Render env: set `BRAIN_MODEL=qwen3-vl:8b-instruct` if it is set there. Add `SUPABASE_SECRET_KEY`, `GATEWAY_TOKEN`, `FALLBACK_LLM_*`, `SARVAM_API_KEY`, `TAVILY_API_KEY` in the dashboard before pushing. Until then the live `/api/*` calls return 500.
- Groq rate limits are per **organization**: rotating keys only helps if they are from different orgs.
- `update_profile` writes the values, then the sources: two calls, not atomic. Move both into one RPC if it ever matters.
- `assistant_settings.language` DB default is still `'mr'` (the UI default is `en`), so a never-saved user on a new device gets `mr` via `loadMe`.
- `NEXT_PUBLIC_API_URL` empty → `public_endpoints` discovery is not built (phone backup only).

## 2026-10-03 · M3 Text agent ✅
**What changed**
- No migration: the live schema already had `profile_proposals`, `form_sessions.phase` and `messages.lang/input_mode/tool_*` (checked with SQL).
- `app/agent/`:
  - `phases.py`: pure `next_phase()`. Core fields incomplete → `onboarding`; complete with no portal → `choose_form`; portal set → `research`. Forward only. `CORE_FIELDS` is 12 fields (PRODUCT.md); trim it there to shorten the demo.
  - `tools/`: a registry that refuses tools outside the current phase, in code. Bad args come back as `{ok:false,error}`.
    - `get_profile` masks caste, religion, mobile and Aadhaar last-4.
    - `propose_profile_update` validates with `ProfileIn` plus the form's gender/category options; `message_id` comes from the orchestrator.
    - `explain_why_asked` uses the i18n templates.
    - `list_supported_forms` and `suggest_schemes` (stub until M5).
    - `set_form` always stores the official URL from code.
  - `orchestrator.py`:
    - Streams replies. Tool calls are assembled by index (Groq sends each one whole in one chunk). At most 6 tool calls per turn, then one final call without tools. The phase is re-synced after each tool round.
    - CJK characters are stripped from replies. Both LLMs down → the i18n apology.
    - One corrective nudge when an onboarding reply mentions a card that was never created. Seen live: Groq said "tap Confirm" without calling the tool.
  - `prompts/`: `system.md`, phase prompts for onboarding, choose_form and research, and `i18n/{en,hi,mr}.json` (the ask/why text for the core fields, plus `llm_unavailable`).
- `app/ws/`:
  - `protocol.py` (pydantic models, mirrored in `web/src/lib/ws/protocol.ts`).
  - `voice.py`, the `/ws/session/{id}` endpoint:
    - Opening: `hello` with the token → user and session checked; closes with 4400, 4401 or 4404. Aster greets first on a new session.
    - Limits: 30 messages/min per connection.
    - Card taps: `form_selected` calls `set_form` in code.
- REST: `POST /api/profile/confirm`. Kept values are saved with source `text` + `{proposal_id, message_id}`; values the user corrected in the card are saved as `manual`; a blanked field is not saved. The audit has field names only. `PUT /api/profile` now writes only the fields that changed, so the form no longer turns chat-confirmed values into `manual`.
- `repo.add_message` keeps only the last 4 digits of Aadhaar- and bank-like numbers (12 digits, or 11–18) in message text and tool payloads (guardrail 6). `update_profile` refreshes `confirmed_at` on every upsert.
- Web:
  - `/chat` opens the latest active session (read through RLS) or creates one.
  - `/chat/[sessionId]`: history and pending cards loaded through RLS, the `useSessionSocket` hook (reconnects with backoff), streaming text, the `ConfirmProfileCard` (editable) and `SchemeSuggestionsCard`, the tool label, and Avatar `thinking`/`happy` states.
- **Privacy fix:** the localStorage profile cache wasn't tied to an account, so a second account on the same browser saw the first one's profile (the "59%" report). It's now cleared when a different user signs in, and on sign-out.
- **Dev fix:** set `NEXT_PUBLIC_API_URL=http://127.0.0.1:8000`, not `localhost`. Browsers send every `localhost` cookie, from any port, with the WS handshake. This browser had about 12 KB of Supabase cookies, and uvicorn/websockets hangs without logging when the Cookie header is over 8 KB (reproduced: 4 KB → 101, 9 KB → timeout). The prod domains don't share cookies. Documented in `web/.env.local.example`.

**How verified**
- pytest **103 passed**: phase table, tools, orchestrator with a fake LLM (card flow, phase refusal, the 6-call cap, apology, CJK, the fake-card nudge), WS (close codes, greeting, card tap → research, rate limit), confirm/reject/edit/foreign-proposal, ID redaction, profile PUT diff. ruff clean. Web lint, typecheck, build and test pass.
- **Live, real DB** (account harshkasliwaal@…, session `45be1a02…`, GPU then Groq):
  - A Marathi sentence → card "Aarav Sunil Patil · 2005-05-12 · Male · Pune" → Confirm → `profiles` updated, `profile_field_sources` rows `text` with `{proposal_id, message_id}`, `profile.confirmed` audit.
  - Category and income went through cards too.
  - "Mahadbt" → audit `phase.changed onboarding→choose_form`, `form.set mahadbt`, `phase.changed choose_form→research`, and `form_sessions` shows `phase=research, portal=mahadbt`. The GPU was stopped mid-run and Groq took over (`provider=fallback`).
- **Live, real LLM, in-memory store** (`scratchpad/live_onboard.py`, Groq): Marathi answers for 10th, 12th and course → 2 real cards → Confirm → `choose_form` → "महाडीबीटी" → `research`, all replies in Marathi.

**Open issues**
- The education fields of the real-DB run went through the profile form, because the faked-card bug hit before the nudge existed. Then the form save turned every source into `manual` (now fixed). A clean single real-DB Marathi run needs an account with empty core fields.
- Models sometimes say "profile updated" before the tap. Nothing is saved until confirm, but the wording is wrong. The prompt is tightened; watch for it.
- `/chat/[id]` takes a few seconds to connect after a reload: loading history plus Supabase `getSession` before the socket opens. Profile it with M4.
- Two tabs on one session run turns at the same time and don't see each other's messages. Fine for now.
- Message `lang` = the session language from `hello`; the model follows the conversation's language, so a Marathi reply can be stored as `en` after a toggle. M4 STT detection fixes this for voice.
- The Marathi and Hindi templates and prompt examples were written by Claude and need a native speaker's review.
- The research phase has no tools until M5: Aster only says research comes next.

## 2026-10-03 · M4 Voice ✅ (manual mic checks pending, see below)
**What changed**
- **No Bhashini** (no credentials, user decision). Chains: STT Sarvam `saaras:v4` → Kaggle `/asr` (hi/mr); TTS Sarvam `bulbul:v3` (mp3, voice `priya`) → `tts_unavailable` → browser `speechSynthesis` (Marathi falls back to a Hindi voice). Vendor docs checked 2026-10-03; models/voices/timeouts in `config.py` with defaults. Removed Bhashini from env example, `render.yaml`, CLAUDE.md, ARCHITECTURE, VOICE.
- `app/speech/`:
  - `router.py`: per-provider timeout (STT 6 s, TTS 5 s) + the existing `Breaker`.
  - `local_gpu.py`: discovers the GPU even when `LLM_PRIMARY=fallback`; that switch is about the brain only.
  - `sentences.py`: splitter (`. ? ! । \n`, 25–220 chars). The first chunk may also end at `, ; :` so Aster starts talking sooner. Number-aware: "3.5" and "1,200" don't split.
  - `normalize_for_tts`: ₹ amounts, dates, masked numbers "ending in 4417", emoji/markdown stripped. **Full Aadhaar/bank numbers are masked via `redact_ids` before TTS** (guardrails 5/6; found by `/guardrails`).
  - `stream.py` `Speaker`: concurrent TTS per sentence, sent in `seq` order. `flush()` before a tool round, so "Thanks!" isn't held through the tool call and the next LLM round. Capped at 15 sentences.
- WS (`app/ws/voice.py`):
  - `audio_start` + one binary frame (≤ 2 MB) + `audio_end`. New messages: `interrupt`, `transcript`, `tts_audio` (+ binary), `tts_unavailable`, `turn_metrics`.
  - Turns run as tasks: `interrupt` or a new utterance cancels the LLM + TTS; UI events queue behind the running turn. A lock keeps each `tts_audio` header next to its binary frame.
  - The detected STT language is stored on the user's message (`input_mode=voice`); the reply language is the toggle (see the language-switch fix below). After a voice turn, card-tap replies are spoken too; typing switches speech off.
- Orchestrator:
  - `REPLY_MAX_TOKENS=800`. The 8B GPU model was seen looping forever: 200+ TTS calls.
  - The fake-card nudge now also matches `confirm|पुष्टी|पुष्टि`. The GPU model said "Confirm बटण दाबा" 22 turns in a row without a card.
- Web:
  - `lib/voice/mic.ts`: Silero v5 VAD via `@ricky0123/vad-web` 0.0.31. Model, worklet and onnxruntime 1.30.0 load from jsdelivr, since a bundled build looks for them at `/`. Hands-free sends WAV; push-to-talk (pointer or Space/Enter) sends webm/opus via MediaRecorder.
  - `player.ts`: WebAudio queue, `AnalyserNode` level, `stop()` for barge-in, drops late audio of interrupted messages.
  - `useVoice.ts`: barge-in, plus client latency from speech end to the first audio heard.
  - `LatencyOverlay` (dev or `?latency`).
  - Avatar `listening` (leans in, ring follows mic level) and `speaking` (mouth/ring follow output amplitude).
  - Chat composer: hold-to-talk + hands-free toggle.
- `/health`: `sarvam_stt` / `sarvam_tts` breaker states (no `bhashini`). Test fixtures `client`/`sid` moved to `conftest.py`.

**How verified**
- pytest **119 passed**:
  - splitter, normalisation, ID masking;
  - STT fallback + breaker skip, timeout, all-down;
  - Speaker order, failures → unavailable, flush, cap;
  - WS voice turn: transcript → reply in detected `hi` → `tts_audio` + adjacent binary → metrics. The voice message is stored with `input_mode=voice, lang=hi`, and no transcript or audio appears in logs.
  - Bad/oversized/stray audio, empty transcript;
  - **interrupt cancels a streaming turn** (no assistant row stored);
  - UI event spoken after voice, typed turn not spoken;
  - nudge on "Confirm बटण".
- ruff check and format clean. Web lint, typecheck, test and build pass.
- `scripts/speech_smoke.py`: Sarvam TTS → STT round trip in mr/hi/en (STT 0.2–0.5 s, TTS 0.7–1.6 s). Kaggle `/asr` direct: 0.9–1.5 s warm, 5.7 s cold.
- **Live voice onboarding** (scratchpad script, through the real `/ws` endpoint: Sarvam-spoken user answers → real STT → real LLM → real sentence TTS; in-memory store, card taps simulated):
  - **Hindi**, Groq brain: 13 spoken turns → `phase=research, portal=mahadbt`, nothing missing, every voice message `lang=hi`. First audio median **1.86 s**, max 2.83 s (one 17 s outlier: Groq rate limit).
  - **Marathi**, Groq brain: 11 spoken turns → `research/mahadbt`, all `mr`. First audio median **1.97 s**, max 3.58 s.
  - **Marathi with `SARVAM_API_KEY=bad`**: full onboarding → `research/mahadbt`. Every STT served by `local_gpu` (1.2–3.5 s). Every sentence went to `tts_unavailable`, so the browser speaks. Breaker: 3 failures → skip, retried once per 60 s.
  - Marathi, **Kaggle GPU brain**: first audio median 5.1 s (3.8–10.6 s; LLM first token 2–6 s on a T4 with tools). The model got stuck at `gender` (fixed by the wider nudge above, not re-run on GPU).
- Chrome (`localhost:3000/chat/…`, local backend): page renders with hold-to-talk + hands-free buttons and the overlay. Hands-free on → "Hands-free on — just talk". Silero model + onnxruntime fetched from jsdelivr (wasm 5.4 s first load, cached after). Mic released when toggled off.

**Open issues**
- **Manual mic checks (user):** a spoken onboarding in Marathi and Hindi in Chrome, the overlay "First audio (heard)" ≤ 3 s, and barge-in. Talk over Aster; the playback stop runs synchronously in the VAD `onSpeechStart` callback (Silero v5 frames are 32 ms), and the console logs `[aster-voice] barge-in…`. Use headphones: echo cancellation is on, but speaker audio can still trigger barge-in.
- **Brain choice decides the ≤ 3 s budget:** Groq ≈ 2 s; the Kaggle T4 ≈ 5 s and was less reliable at tool calls. Groq's free tier (7 k input tokens/min, about 3 turns/min) 429s in fast conversations; the live runs were paced 20 s/turn. For the demo, either a paid/other fallback org or accept GPU latency.
- A nudged turn speaks (and shows) both the wrong "tap Confirm" sentence and the corrected one (M3 behaviour, now audible).
- STT mistakes seen: "बी ई" heard as "भी" (Hindi), so `current_course` became "Computer". The confirm card catches it, but a `keyterms` list (saaras:v4) with course names would help.
- The interrupted (barged-in) reply is not stored in history.
- jsdelivr is a runtime dependency for the VAD; self-host the assets under `web/public/vad/` if the demo network is flaky.
- Render: blank `SARVAM_*_MODEL` vars fall back to the config defaults (`env_ignore_empty`); the old `BHASHINI_*` vars can be deleted in the dashboard.

### 2026-10-03 · M4 follow-up: language toggle
- **Bug (user click-through):** switching the reply language had no effect until the user asked aloud. Cause: voice turns set the reply language from the STT-detected language, overriding the toggle; and with Marathi history, even a correct system prompt lost (Groq qwen replied in Marathi to "Reply in Hindi only", once claiming in Marathi that it answers only in Hindi).
- **Fix:** reply language = the toggle (`hello.lang`) for every turn; the detected language is still stored on the user's message. The LLM request appends a target-language note to the newest user turn (`i18n reply_in`, e.g. "कृपया अब से केवल हिंदी में जवाब दें, मराठी में नहीं।"); stored messages are unchanged. System prompt: "Reply only in {lang} … even if earlier messages use another language".
- **Verified:** live Groq, Marathi history + Marathi speech, toggle Hindi → Hindi 4/4 (2 more runs were rate-limit apologies, also in Hindi); toggle English → English. An English-worded note was flaky for Hindi; a bracketed note once produced "[assistant turn 4]". pytest 120 passed (new: note only on the latest user turn, stored text/lang untouched, reply lang = toggle).

## 2026-10-03 · M5 Research + eligibility ✅ (packs await team verification)
**Scope change (user):** any scholarship, not only MahaDBT. MahaDBT has separate schemes per category, and private ones (LIC etc.) count too.

**What changed**
- **Migration `0004_scheme_research`:** `form_sessions.scheme_name` (a scheme without a pack) and `research_results.scheme` (which scheme the research is about). Applied via MCP; types regenerated; advisors unchanged.
- **Knowledge packs (all `draft`):** 7 packs, every quote copied word for word from the official page or PDF.
  - MahaDBT: GOI Post-Matric SC, GOI Post-Matric ST, Shahu Maharaj EBC, Post-Matric OBC, Panjabrao Deshmukh hostel (DHE).
  - LIC Golden Jubilee 2026 (general track).
  - NSP Central Sector Scheme (CSSS).
  - Portal metadata lives in `knowledge/<portal>/_portal.json`; `_TEMPLATE` moved to `knowledge/`.
  - Rules that can't be checked from the profile ("no other scholarship", "first two children", hostel) are criteria with `logic: null`, so they show as ❔.
  - **EWS is accepted for the "general category" schemes. This is flagged VERIFY in those packs' notes.**
- `app/verify/rules_engine.py`: a JSON Logic subset with three-valued results. A missing var gives unknown; and/or follow Kleene logic. Shared with M6.
- `app/research/`:
  - `search.py`: Tavily `/search` with `include_domains_mode=prefer`; official domains ranked first; 10 s timeout; breaker.
  - `fetch.py`: SSRF guard on every redirect hop (http(s), public IPs only); 5 MB / 10 s caps; whole-page text via `trafilatura.html2txt`. The library's main-content mode returned a hidden modal table on MahaDBT pages and dropped the eligibility section.
  - `fetch.py` also has `excerpt()` (focus words counted at most twice per chunk, plus the scheme name) and `quote_in()` (NFKC, plain quotes and dashes, casefold, whitespace).
  - `pdf.py`: pymupdf; scanned pages go to the GPU `/ocr` (≤ 15 pages).
  - `packs.py`: the pydantic `Pack` model, loader and `validate` CLI. Logic vars must be `profile.<column>`; doc types must match the DB check constraint.
- **Tools:**
  - `get_knowledge_pack`, `search_web`, `fetch_url`, `read_pdf`.
  - `save_research` (quote validator): the `content_id` must belong to this session, `source_url` must be that page, and the quote must be ≥ 15 chars and found on the page.
  - `check_eligibility`: a pack gives ✅/❌/❔ "… — per <site>" with `ask_field`; a live scheme gives all ❔ unverified.
  - Real `suggest_schemes`: ranked across all portals, top 6, with counts.
  - `set_form(scheme_key | scheme_name)`.
- **Phases:** `choose_form → research` once a scheme is set; `research ↔ eligibility` follows "research saved for the current scheme", so switching scheme goes back to research. `suggest_schemes` and `set_form` stay available in research and eligibility.
- **Orchestrator:**
  - `run_tool_ui` is shared by the LLM loop and card taps.
  - Research-phase replies are held until checked. If the model typed rules after reading pages without `save_research`, the text is dropped and it is nudged to save quoted items (seen live with the 8B GPU model).
- **Card tap** (`form_selected {scheme_key}`): `set_form` → `get_knowledge_pack` → `check_eligibility` run in code; the LLM only speaks the summary.
- `/health`: `tavily: up|open|missing` and `packs: {usable, total}`.
- Config: `PACKS_INCLUDE_DRAFT`, dev only, ignored when `APP_ENV=prod`; cards show DRAFT. Plus search/fetch/PDF/OCR limits.
- **Web:**
  - `EligibilityCard` (✅/❌/❔, reason, official quote + link, DRAFT/Unverified badges, deadline passed).
  - `ResearchSummaryCard` (items "Unverified — from <site> on <date>", rejected count).
  - The suggestions card shows counts.
  - Eligibility and research cards come back after a reload (from their tool rows).
  - Copy no longer says MahaDBT only.
- Docs: AGENT, API, RESEARCH, PRODUCT, knowledge/README, CLAUDE.md, README.

**How verified**
- pytest **188 passed**: rules engine (24 cases); SSRF (localhost/10./169.254/192.168/::1, schemes, redirect to an internal host); HTML/PDF/size cap; scanned PDF without GPU; excerpt; quote normalisation; Tavily ranking + breaker; real packs parse offline; pack validation errors; drafts dev-only.
- More tests: the eligibility card has no verdict wording; **a fabricated quote is rejected** (plus misattributed URL, short quote, unknown `content_id`, another session's content); a mixed save keeps only the good items; a live-research turn end to end; typed rules are held and nudged; the WS card-tap path; phases. ruff clean.
- Web lint, typecheck, test and build pass.
- `uv run python -m app.research.packs validate` (online): **OK**. All 7 packs: every URL loads through `fetch.py` and every quote is found.
- **Live, real `/ws`** (real Supabase DB, Groq brain, Sarvam; JWT check bypassed for user `7704a395…`, EWS / ₹1 L / Maharashtra; `PACKS_INCLUDE_DRAFT=true`):
  - **A** (session `7525dda6…`):
    - Spoken "मला महाडीबीटीची शिष्यवृत्ती भरायची आहे" → Sarvam STT 0.6 s → `scheme_suggestions`: Panjabrao 3 met / 0 not met, EBC 3/0, SC 3/1, OBC 3/1, ST 2/1.
    - Tap Panjabrao → `set_form` → research → `get_knowledge_pack` → eligibility → card (3 ✅, 3 ❔, mahadbt.maharashtra.gov.in links).
    - Marathi summary "अधिकृत नियमांनुसार … ६ पैकी ३ अटी जुळतात … अंतिम निर्णय योजना विभागाचा असेल", spoken in 4 TTS chunks, first audio 1.1 s.
  - **B** (session `8e610561…`, Kaggle GPU brain):
    - "Tata Capital Pankh Scholarship" → `set_form(scheme_name)` → Tavily → 3 fetches → `save_research` kept 3 items, **rejected 1** → `research_summary` "Unverified · tatacapital.com" → eligibility.
    - SQL: every saved quote is in its `fetched_content` text and every `source_url` matches its content.

**Open issues**
- **TEAM: verify the 7 packs.** Open every `source.url`, check every quote and value (especially the EWS note), then set `status: "verified"`, `verified_by` and `verified_on`. Until then the demo needs `PACKS_INCLUDE_DRAFT=true` (dev only); prod offers no packs.
- **Groq free tier can't do live research:** one research turn is 4–6 LLM rounds of ~4k tokens, over 7k tokens/min, so it returned 429s. A 429 also counts as a breaker failure. Use the GPU brain (B took ~63 s) or a paid fallback.
- The research turn on the GPU is slow (~50–60 s); tool labels show progress, but the demo should use pack schemes.
- A live item's `text` is the model's paraphrase; only its quote is checked. The card shows both.
- Render: check `/health` → `packs.total` = 7. `knowledge/` is outside `rootDir: backend`; if it is 0 there, the packs didn't ship.
- Manual Chrome click-through of the new cards is pending (steps in the M5 hand-off).
- Live test sessions `0307fa22…`, `7525dda6…`, `b7d512a3…`, `40220154…` and `8e610561…` were created on the dev account `7704a395…`.

### 2026-10-03 · Follow-up: "ठीक है, अब से मैं केवल हिंदी में ही जवाब दूँगा" on every reply
- **Bug (user screenshots):** after switching to Hindi, every reply started by acknowledging the switch, in every chat.
  - Cause: the M4 language note ("कृपया अब से केवल हिंदी में जवाब दें…") was added to the latest user turn on every request. The model answered it as if the user had asked, then copied that line from its own history.
- **Fix (`orchestrator.py`):**
  - The note is added only while the last 12 messages contain another language.
  - It is worded as a silent instruction: "(उत्तर हिंदी में लिखें। भाषा के बारे में कुछ न कहें।)", i.e. "answer in Hindi; say nothing about the language".
  - `strip_lang_ack()` removes sentences that say "only + language + reply" from the history the model sees (so already-polluted chats recover) and from the stored/final reply as a backstop.
- **Verified:**
  - pytest 193 passed (new: no note when there is nothing in another language; acknowledgements dropped from history and reply; strip keeps normal sentences such as "₹1.5 lakh" and "English, Hindi or Marathi").
  - Live, Groq, a session with Marathi history: toggle Hindi → 3/3 replies in Hindi with no acknowledgement; toggle English → English.
- **Seen during that run:** a turn crashed with `httpx.RemoteProtocolError: Server disconnected` from the Supabase client (idle HTTP/2 connection dropped). The user saw "something went wrong". Not fixed yet.

### 2026-10-03 · Follow-up: "Sorry, I can't think right now" on "reliance foundation scholarship"
- **Cause:** `LLM_PRIMARY=fallback` (Groq only; the Kaggle GPU was up but skipped). Researching an unknown scheme takes 6–7 LLM rounds of ~4–6k tokens, and Groq allows 8k tokens/min. The 429s were treated as "provider down", so the turn ended in the apology. In the same turn a PDF read hung for 55 s and one page was fetched twice.
- **Fixes:**
  - `llm/client.py`: a 429 means wait, not down. It waits for Groq's "try again in Xs" or `retry-after` (≤ 30 s, at most 2 retries per call) and does not touch the breaker.
  - `research/fetch.py`: a 20 s total download deadline (`FETCH_TOTAL_S`); the httpx timeout is only per read.
  - `fetch_url`/`read_pdf`: reuse a page already fetched in the session.
  - Orchestrator: tool-call markup the model types as text (`<tool_call>…`, seen on Groq after the tool cap) is never shown, spoken or stored. When the research cap is hit with pages read but nothing saved, one extra `save_research` is allowed.
- **Verified:**
  - pytest 198 passed (new: rate-limit wait + retry, give up when the wait is too long or keeps repeating, fetch deadline, fetch reuse, cap + markup).
  - Live retest on Groq: no apology any more, but a research turn takes up to ~170 s (rate-limit waits) and some turns ended at the cap; these two fixes followed that run.
- **Recommendation:** run with `LLM_PRIMARY=gpu` while Kaggle is up (Groq stays the automatic backup), or use a higher-limit hosted fallback.

### 2026-10-03 · Follow-up: research on the GPU ("Let me check…" and the apology again)
- **14:54 (GPU):** the reply was only "Let me check… Let me read…" and no tool ran. Replayed twice: the model copies earlier narration-only replies (the history keeps text, not tool calls). Fix: a research reply with no tool call is held (never shown) and nudged once to call the tool.
- **14:51:** the model passed links without a scheme ("site.org/page") and fetch rejected them. Fix: `https://` is added, and the SSRF checks still apply.
- **14:59 (GPU):** search → page → UG FAQ PDF read fine, then the apology. Replaying the exact request: the GPU's first chunk took **11.8 s** and was a correct `save_research` with official quotes. Ollama sends tool calls only when complete, and the 8 s first-chunk limit discarded it. Groq (the fallback) was rate-limited, partly because my own live test was running at the same time. Fix: a 30 s first-chunk limit when tools are offered.
- pytest 201 passed.

### 2026-10-03 · Follow-up: search 400, "Bajaj Finserv" promise-only reply
- **Search "failed" (15:08):** the model passed `*.reliancefoundation.org` / `*.gov.in`, and Tavily answers 400 in prefer mode. Fix: `*.` is stripped before the call. The research prompt also forbids typing links that didn't come from a tool (it had invented `reliancefoundation.org/scholarships`). After the fix, the Reliance research worked for the user.
- **"what about this Bajaj finserv scholarship" (eligibility step, 15:21):** the reply was three "Let me check…" sentences with no tool call, so the scheme never switched. The GPU was down (Kaggle stopped), so Groq answered.
  - Fix: in every phase but onboarding, a reply that only promises to act (`promise_only`: Let me / I'll / देखती हूँ / पाहते …) is nudged once to call the tool, `set_form` first if the user named another scholarship.
  - Promise sentences are also dropped from the history the model sees, since the model copies them.
- Noted: the user's `.env` has no `PACKS_INCLUDE_DRAFT`, so `/health` shows `packs.usable: 0` until the packs are verified.
- pytest 208 passed.
- **Infocepts (15:32, GPU):** set_form → search → fetch → save_research worked end to end (47 s). But the closing line "3 of 5 criteria look met…" was the prompt's example, copied word for word; check_eligibility never ran. Fix: after a successful `save_research` moves the session to eligibility, `check_eligibility` runs in code and the model gets its real counts. The prompt examples now use placeholders, plus a rule: researched schemes are all unknown, never "N of M met". pytest 208 passed.
