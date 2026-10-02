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
