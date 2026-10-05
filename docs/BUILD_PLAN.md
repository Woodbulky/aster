# Build plan

Run each milestone with `/milestone M<n>` in Claude Code. Do them in order. Each one ends with a working demo path and a commit.
Tick the box when its acceptance criteria are verified.

## Status
- [x] M0 Scaffold
- [x] M1 Supabase schema + auth + onboarding UI
- [x] M2 Backend core (auth, LLM client, GPU discovery, health)
- [x] M3 Text agent (WS, phases, onboarding + choose_form)
- [x] M4 Voice (VAD, STT/TTS router, avatar states, barge-in)
- [x] M5 Research + eligibility (packs, live research, cards) — packs are drafts until the team verifies them
- [x] M6 Documents + verification (OCR, extraction, contradictions, rules) — Realtime trimmed (poll + server push)
- [ ] M7 Guided form filling (screen share, PiP, guidance) — built; acceptance verified live over the real WS + model + TTS with mock-portal screenshots; browser click-through (share picker, PiP, Private mode, mic) and GPU latency pending
- [x] M8 Audit, consent, profile page, polish — UI stays English (user decision); i18n = agent/card text only
- [ ] M9 Demo hardening
- [ ] Scheme requirements + per-cycle catalogue (2026-10-05) — code done: requirement ids/conditions/questions, cycle-scoped packs and research, freshness labels; open: a human verifies 2–3 packs for 2026-27 (until then prod has 0 usable packs)

---

## M0 — Scaffold
**Read:** CLAUDE.md, ARCHITECTURE.md, FRONTEND.md
**Build:** `backend/` with uv (FastAPI app, `config.py` via pydantic-settings reading `.env`, `/health` returning `{status:"ok", version}`, ruff + pytest set up, one passing test). `web/` with Next.js App Router + TS strict + Tailwind + shadcn/ui init, pnpm scripts `dev/lint/typecheck/build`, a landing page with the brand colours from FRONTEND.md. Root `.gitignore`, `README.md` (how to run). Root `render.yaml` Blueprint: one `type: web` service, `runtime: python`, `rootDir: backend`, `region: singapore`, `plan: free`, `healthCheckPath: /health`, `autoDeployTrigger: commit`, `buildCommand: uv sync --frozen --no-dev`, `startCommand: uv run --no-sync uvicorn app.main:app --host 0.0.0.0 --port $PORT`; every key from `backend/.env.example` as an `envVars` entry with `sync: false` (Render uses uv only when `backend/uv.lock` is committed; pin Python 3.12 with `backend/.python-version` — Render's default is 3.14 — or `PYTHON_VERSION` set to a full `3.12.x`; per render.com/docs/uv-version + /docs/python-version, checked 2026-10-02). Keep the existing `docs/`, `supabase/`, `gpu/`, `knowledge/`, `ops/` folders untouched.
**Accept:** `uv run pytest` passes; `curl localhost:8000/health` ok; `pnpm build` passes; `pnpm dev` shows the landing page; Render deploy returns `/health` ok (`curl https://<service>.onrender.com/health`).

## M1 — Supabase schema + auth + onboarding UI
**Read:** CLAUDE.md (Supabase rules), `supabase/migrations/0001_init.sql`, FRONTEND.md
**Build:** Apply `0001_init` via Supabase MCP `apply_migration`. Run the advisors and fix findings in `0002_*.sql` if needed. Generate types to `web/src/lib/database.types.ts`. Web: Supabase SSR client + middleware, `/login` (Google + email magic link), `/onboarding` avatar picker (4 avatars, SVG orb with eyes + idle animation), name + language → saved via backend later (for now direct `PUT /api/assistant` stub is fine; mark TODO).
**Accept:** Sign-up creates `profiles` + `assistant_settings` rows (show via MCP SQL); logged-out users are redirected to `/login`; the avatar picker animates; advisors show no RLS errors.

## M2 — Backend core
**Read:** ARCHITECTURE.md, API.md
**Build:** JWT verification dependency (`supabase.auth.get_user`); repositories for sessions/messages/profile; `app/llm/client.py` (OpenAI-compatible, streaming + tools + images; resolves the GPU URL from `gpu_endpoints` with a 30 s cache; falls back to `FALLBACK_LLM_*`; circuit breaker); `/health` with provider states; `PUT /api/assistant`, `GET /api/me`, `POST /api/sessions`; CORS from env.
**Accept:** With the Kaggle notebook running, `/health` shows `gpu: up` and a test script streams a Marathi reply through the gateway; with the notebook stopped, the same script uses the fallback within 8 s. Unit tests cover the breaker and URL discovery. `LLM_PRIMARY=fallback` never queries `gpu_endpoints` (test). A sensitive (image) call served by the fallback writes an `llm.sensitive_fallback` audit event with no image content (test). (Routing policy + `/health` `llm` field already exist from the LLM_PRIMARY change; M2 wires discovery + breaker into `gpu_url()`.)

## M3 — Text agent
**Read:** AGENT.md, API.md
**Build:** WS endpoint + typed protocol (pydantic ↔ `web/src/lib/ws/protocol.ts`); orchestrator with the phase machine; tools for `onboarding` and `choose_form` (`get_profile`, `propose_profile_update`, `explain_why_asked`, `list_supported_forms`, `suggest_schemes` stub, `set_form`); `POST /api/profile/confirm`; prompts in `app/agent/prompts/`; i18n templates for the core onboarding fields. Web `/chat/[sessionId]`: message list, streaming text, cards `confirm_profile` and `scheme_suggestions`, avatar state from `agent_state`, tool activity label.
**Accept:** By text in Marathi, a new user completes onboarding (confirm card → profile saved with `profile_field_sources`), says "MahaDBT", and the session moves to `research`. Tests for phase transitions.

## M4 — Voice
**Read:** VOICE.md, API.md, FRONTEND.md (avatar)
**Build:** Speech router + Sarvam + Bhashini + local_gpu providers (fetch the vendor docs first; models in config); WS audio in/out; sentence streaming TTS; `tts_unavailable` fallback; web VAD, push-to-talk, playback queue, barge-in, avatar `listening/speaking` with amplitude; dev latency overlay.
**Accept:** A full onboarding by voice in Marathi and in Hindi; first audio ≤ 3 s typical (overlay evidence); interrupting Aster stops the audio within 300 ms; disabling Sarvam (bad key) still works via Bhashini/local.

## M5 — Research + eligibility
**Read:** RESEARCH.md, `knowledge/README.md`, AGENT.md
**Build:** `search.py` (Tavily), `fetch.py` (httpx + trafilatura; store in `fetched_content`), `pdf.py` (pymupdf; scanned → GPU OCR), `packs.py` (load + validate CLI), JSON Logic engine (shared with M6 — build it here with tests), tools `get_knowledge_pack`, `search_web`, `fetch_url`, `read_pdf`, `save_research` (quote validator), `check_eligibility`, real `suggest_schemes`. Cards `research_summary`, `eligibility`. Draft 3 demo packs from official sources → the TEAM verifies them (stop and ask me to verify before marking them verified).
**Accept:** "MahaDBT" → scheme suggestions → pick one → eligibility card with ✅/❌/❔ + working source links, spoken summary. An unknown scheme triggers live research with quote-validated items labelled unverified. An item with a fabricated quote is rejected (test).

## M6 — Documents + verification
**Read:** VERIFICATION.md, API.md
**Build:** Client upload to Storage + blur check; `POST /documents` → background pipeline (render PDF, classify, `/ocr`, extract with line ids, validator, candidates); `names.py` + tests; contradictions; rules engine files + 6 starter rules; flags; resolve/acknowledge endpoints; cards `document_checklist`, `field_review` (document viewer with bbox highlight), `contradiction`, `missing_item`, `low_confidence`, `readiness`; Realtime progress.
**Accept:** With the seeded demo documents (see M9), an income contradiction and a passbook name variation are flagged and resolved by voice; every field shows its source; the validator rejects a value not present in the OCR lines (test); name matcher tests pass.

## M7 — Guided form filling
**Read:** FORM_FILL.md
**Build:** `/fill/[sessionId]`: screen share, frame policy (dHash change detection), Document PiP window with the avatar + instruction + copy; WS `screen_frame`; `analyze_screen` + code post-processing (sensitive pages, value whitelist, identifier rule); `guidance` + `pause_guidance` events.
**Accept:** On a local mock portal page (build `web/public/mock-portal/` with login, OTP, form and submit pages) Aster guides 5 fields by voice, refuses OTP/password, pauses at submit; frames are never written (grep the logs/DB).

## M8 — Audit, consent, profile, polish
**Build:** Consent screens before sensitive fields + document processing; the audit trail view; `/profile` with sources + edit (edits = new confirmed value + audit) + delete my data; `/sessions`; error/empty states; i18n pass on all UI strings; accessibility pass.
**Accept:** The audit chain verifies (a script recomputes hashes); delete-my-data removes rows + storage objects; Lighthouse accessibility ≥ 90 on `/chat`.

## M9 — Demo hardening
**Build:** Seed script for a demo user + specimen documents (synthetic, watermarked SPECIMEN, no real IDs); a "demo mode" switch that preloads the pack; a fallback drill script (stop the GPU → verify fallbacks); a rehearsal checklist in `docs/DEMO.md`; record a backup demo video.
**Accept:** Two full rehearsals of the PRODUCT.md demo script without manual fixes, one with the Kaggle worker killed mid-demo.
