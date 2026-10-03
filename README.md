# Aster

A multilingual voice + chat assistant that helps students research, verify, and fill government application forms (any scholarship; verified rule packs for MahaDBT, NSP and LIC).

**Start here:** `docs/SETUP_GUIDE.md`. Then open Claude Code in this folder and run `/status`, then `/milestone M0`.

| Path | What |
|---|---|
| `CLAUDE.md` | Context Claude Code loads every session (stack, rules, guardrails) |
| `docs/` | Product, architecture, agent, voice, research, verification, form-fill, frontend, API specs + build plan + setup guide |
| `.claude/commands/` | `/milestone`, `/guardrails`, `/status` |
| `supabase/migrations/0001_init.sql` | Full schema with RLS, storage bucket, audit hash chain, endpoint registration |
| `gpu/aster_gpu_worker.ipynb` | Kaggle 2×T4 worker (LLM/vision + ASR + OCR behind one authenticated gateway + Cloudflare tunnel) |
| `render.yaml` | Reference copy of the Render backend service settings (live service was created manually; web goes to Vercel) |
| `ops/phone/` | Optional backup: Termux scripts to run the backend + tunnel on the phone |
| `knowledge/` | Verified scheme packs (template inside) |
| `backend/`, `web/` | Built by Claude Code from M0 (env examples included) |

## Run locally
```bash
# backend → http://localhost:8000/health
cd backend && cp .env.example .env && uv sync
uv run uvicorn app.main:app --reload --port 8000
uv run pytest -q && uv run ruff check . && uv run ruff format --check .

# web → http://localhost:3000
cd web && cp .env.local.example .env.local && pnpm install
pnpm dev
pnpm lint && pnpm typecheck && pnpm build
```
Deploy: push to `main` → Render redeploys the backend (`https://aster-jj5b.onrender.com`); setup in `docs/SETUP_GUIDE.md` Phase 5b.
