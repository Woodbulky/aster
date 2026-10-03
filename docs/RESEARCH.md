# Research — eligibility & documents

## Strategy: verified packs first, live research second
1. **Knowledge pack** (`knowledge/<portal>/<scheme>.json`, `status: "verified"`): curated by the team from official sources. Every criterion and document carries `source.url` + `source.quote`. Used for the demo schemes. Fast and reliable.
2. **Live research** (any other scheme/form or a user-provided URL):
   - Any scholarship (government or private): `set_form(scheme_name=…)`, then `search_web` (Tavily, `include_domains_mode=prefer`). `*.gov.in`, `*.nic.in` and `prefer_domains` (e.g. the scheme owner's site) rank first; 1–2 queries.
   - `fetch_url` on the top official pages (SSRF guard on every hop; whole-page text via `trafilatura.html2txt`, because its main-content guess dropped the scheme section on MahaDBT pages; the LLM gets the ~2k chars most about `focus` + the scheme name). `read_pdf` for GR/notification PDFs (often Marathi; scanned ones → GPU OCR).
   - The LLM extracts structured items. **`save_research` rejects any item whose quote isn't found in the fetched content.**
   - Live results are labelled "unverified — from <site> on <date>" in the UI. Research-phase replies are held until the turn is checked: if the model typed rules without `save_research`, they are dropped and it is told to save quoted items.
   - `check_eligibility` on a live scheme shows every saved rule as ❔ "unverified — check this rule yourself": only verified packs get ✅/❌.
3. If research fails → say so, show the official portal link, and continue with what's known.

## Scheme discovery
A portal like MahaDBT has many schemes (SC, ST, OBC, EBC, hostel, …). `suggest_schemes` evaluates every pack's criteria against the profile and shows the top 6, ranked by fewest not met, then most met, with met/not met/unknown counts. A tap runs `set_form` → `get_knowledge_pack` → `check_eligibility` in code (no LLM tool calling on the demo path). The user picks one, or the agent asks 1–2 clarifying questions (course type, category).

## Eligibility evaluation (deterministic)
- Pack `criteria[].logic` is a JSON Logic subset (`app/verify/rules_engine.py`: var, == != < <= > >= (3-arg = between), and/or (Kleene), !, !!, in, if) over `profile.*`. Strings compare trimmed and case-insensitive. `computed.*` is not built yet (no pack needs it).
- Result per criterion: `met` / `not_met` / `unknown` (any referenced var missing → `unknown`, plus a question to ask).
- The LLM only phrases the result. The card shows each criterion with its source link.

## Pack authoring workflow (team task, M5)
1. Pick 3–5 demo schemes.
2. Ask Claude Code to draft each pack from fetched official pages/PDFs (quotes copied verbatim).
3. A human opens every `source.url`, checks every quote and value, sets `status: "verified"`, `verified_by`, `verified_on`.
4. `uv run python -m app.research.packs validate` must pass (schema + logic vars + quote present + URLs reachable; `--offline` skips the network).
5. Dev only: `PACKS_INCLUDE_DRAFT=true` (ignored when `APP_ENV=prod`) offers draft packs, badged DRAFT.

Never invent criteria, income limits, deadlines or document lists. If a value can't be sourced, leave it out and add a `notes` entry.
