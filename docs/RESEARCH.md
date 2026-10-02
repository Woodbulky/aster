# Research — eligibility & documents

## Strategy: verified packs first, live research second
1. **Knowledge pack** (`knowledge/<portal>/<scheme>.json`, `status: "verified"`): curated by the team from official sources. Every criterion and document carries `source.url` + `source.quote`. Used for the demo schemes. Fast and reliable.
2. **Live research** (any other scheme/form or a user-provided URL):
   - `search_web` with `prefer_domains` = official domains (`mahadbt.maharashtra.gov.in`, `maharashtra.gov.in`, `*.gov.in`, `*.nic.in`), 2–4 queries in en + mr.
   - `fetch_url` on the top official pages. `read_pdf` for GR/notification PDFs (often Marathi; scanned ones → GPU OCR).
   - The LLM extracts structured items. **`save_research` rejects any item whose quote isn't found in the fetched content.**
   - Live results are labelled "unverified — from <site> on <date>" in the UI.
3. If research fails → say so, show the official portal link, and continue with what's known.

## Scheme discovery
"MahaDBT" is a portal with many schemes. `suggest_schemes` evaluates every verified pack's criteria against the profile and shows the top matches with met/unknown counts. The user picks one, or the agent asks 1–2 clarifying questions (course type, category).

## Eligibility evaluation (deterministic)
- Pack `criteria[].logic` is JSON Logic over `profile.*` and `computed.*` (e.g. `computed.age_on_cutoff`).
- Result per criterion: `met` / `not_met` / `unknown` (any referenced var missing → `unknown`, plus a question to ask).
- The LLM only phrases the result. The card shows each criterion with its source link.

## Pack authoring workflow (team task, M5)
1. Pick 3–5 demo schemes.
2. Ask Claude Code to draft each pack from fetched official pages/PDFs (quotes copied verbatim).
3. A human opens every `source.url`, checks every quote and value, sets `status: "verified"`, `verified_by`, `verified_on`.
4. `uv run python -m app.research.packs validate` must pass (schema + quote present + URLs reachable).

Never invent criteria, income limits, deadlines or document lists. If a value can't be sourced, leave it out and add a `notes` entry.
