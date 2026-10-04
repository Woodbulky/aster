# Research — eligibility & documents

## Strategy: verified packs first, live research second
1. **Knowledge pack** (`knowledge/<portal>/<scheme>.json`, `status: "verified"`): curated by the team from official sources. Every criterion and document carries `source.url` + `source.quote`. Used for the demo schemes. Fast and reliable.
2. **Live research** (any other scheme/form or a user-provided URL):
   - Any scholarship (government or private): `set_form(scheme_name=…)`. **Shared cache first:** if another student already researched a scheme with this name (`research_cache`, exact or ≥ 92 fuzzy match, < 30 days old), its quote-checked items are copied into the session and the phase moves on with no LLM research rounds (audit `research.reused`). `save_research` writes the cache; `scripts/promote_research.py` turns a cache row into a draft knowledge pack for review.
   - Otherwise **`research_scheme` (one step, 2 LLM rounds in all with `save_research`):** search = Tavily (`include_raw_content: "text"`, `include_domains_mode=prefer`), then Context.dev `/web/search` when Tavily is down or found nothing official. The 3 pages read are the ones *about* the scheme first (its distinctive name words in title/link count double; seen live: preferring tatacapital.com brought a WhatsApp page), official next. Pages come with the search; any that didn't are read side by side (`fetch.fetch`, then Context.dev `/web/scrape` for a 403, a JS-only page or a scanned PDF). Measured: 2–4 s for search + 3 pages ("Tata Capital Pankh", 2026-10-04).
   - Sharing is limited to pages a search engine found (`fetched_content.via = 'search'`, migration 0009): items quoted from a link a student pasted stay in that session (/guardrails: one student must not put "rules" in front of another). Shared text goes through `redact_ids`.
   - Context.dev verified live 2026-10-04: `/web/scrape` of scholarships.gov.in → "NSP : National Scholarship Portal", 5,365 chars, 10.5 s, 1 credit; `/web/search` "Tata Capital Pankh…" → 10 results all with page text, 11.5 s, 2 credits (slower than Tavily's 2–4 s: right as the fallback).
   - Follow-ups: `search_web`, `fetch_url`, `read_pdf` (same page chain). The state lists pages already read this session so a later turn saves instead of searching again.
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
