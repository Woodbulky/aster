# Aster

A multilingual voice + chat assistant that helps students research, verify, and fill government application forms (demo: MahaDBT).

**Start here:** `docs/SETUP_GUIDE.md`. Then open Claude Code in this folder and run `/status`, then `/milestone M0`.

| Path | What |
|---|---|
| `CLAUDE.md` | Context Claude Code loads every session (stack, rules, guardrails) |
| `docs/` | Product, architecture, agent, voice, research, verification, form-fill, frontend, API specs + build plan + setup guide |
| `.claude/commands/` | `/milestone`, `/guardrails`, `/status` |
| `supabase/migrations/0001_init.sql` | Full schema with RLS, storage bucket, audit hash chain, endpoint registration |
| `gpu/aster_gpu_worker.ipynb` | Kaggle 2×T4 worker (LLM/vision + ASR + OCR behind one authenticated gateway + Cloudflare tunnel) |
| `ops/phone/` | Termux scripts to run the backend + tunnel on the phone |
| `knowledge/` | Verified scheme packs (template inside) |
| `backend/`, `web/` | Built by Claude Code from M0 (env examples included) |
