# Knowledge packs

One JSON file per scheme: `knowledge/<portal>/<scheme_slug>.json`, following `knowledge/_TEMPLATE.scheme.json`. Each portal folder has a `_portal.json` (`{name, url}`); `url` becomes the session's `portal_url`.

Current packs: Reliance Foundation Undergraduate Scholarship 2026-27 (`verified`). Drafts until the team verifies them: MahaDBT GOI Post-Matric SC, GOI Post-Matric ST, Shahu Maharaj EBC, Post-Matric OBC, Panjabrao Deshmukh hostel (DHE); LIC Golden Jubilee (general, 2026); NSP Central Sector Scheme (CSSS).

Rules:
- Every criterion, document, and deadline needs `source.url` (official site/GR PDF) and `source.quote`, copied verbatim (Marathi is fine).
- `status: "draft"` until a team member has opened every URL and checked every quote and value, and that each rule applies **to this academic year and route** (a quote alone doesn't establish that). Then set `"verified"`, `verified_by`, `verified_on` (the rules check), `academic_year`, `apply_url` (this cycle's application portal) and `deadlines_checked_on`. `route` is `fresh`, `renewal` or `both`.
- Only verified packs **for the current academic year** are offered (`ACADEMIC_YEAR`, else from the date; the year starts in June). Last year's pack is not shown as verified.
- Two clocks: rules are rechecked every 180 days, deadlines and the portal every 14 (`PACK_RULES_MAX_AGE_DAYS`, `PACK_DEADLINES_MAX_AGE_DAYS`). A stale pack stays usable; its card says when it was last checked. `uv run python -m app.research.packs stale` lists what is due.
- `_portal.json` `cycles`: per academic year, the application portal and the official notice that says so, e.g. MahaDBT 2026-27 → `https://mahadbt2.maharashtra.gov.in/`. A session's `portal_url` = the pack's `apply_url`, else the cycle's URL, else `url`.
- `logic` is JSON Logic over `profile.<profiles column>`, `answers.<question id>` (a question declared in `questions`: Aster asks it at the eligibility step, only for this scheme) and `computed.cycle_start` (the pack's `academic_year` start, e.g. 2026: use it for "admitted in 2026-27" with `profile.admission_year`). See docs/RESEARCH.md for the operators. Check what the rule says, not a stand-in: "approved course" is a question (`course_approved`), not "has an SSC year". Put every condition a student can answer into `logic` or a question; leave `logic: null` only for a rule nobody can answer for them (an attendance promise, a board's percentile table): it shows "needs confirmation, read it at the source".
- `applies_if` (+ `applies_note`, required with it) says when a rule is relevant at all, e.g. `answers.professional_course == yes` for the professional-course income limit. False → "not applicable", shown but not counted; unknown → asks that question first. Write alternatives with `and`/`or` (three-valued), not `if`.
- Education path: `profile.entry_qualification` is what the course was joined after (`ssc` = after 10th: diploma, ITI, 11th-12th; `hsc`; `diploma` = lateral entry; `graduation`). 12th details are not asked on `ssc`/`diploma`: a rule that needs them reads "needs confirmation, check the rule for your route" (never a verdict). "Passed 10th" is `or(!!profile.ssc_year, !!profile.entry_qualification)`. Other stable facts: `profile.course_mode` (regular / part_time / distance / online), `profile.admission_year`.
- Never invent limits, amounts, deadlines or document names. Missing info goes in `notes`.
- Documents are requirements (`app/verify/requirements.py`), each tracked on its own:
  - `id`: unique in the pack (defaults to `doc_type`). Two `other` documents need two ids.
  - `also_accepts`: other document types that satisfy the same requirement ("admission letter or fee receipt" is one requirement).
  - `required_if`: JSON Logic over `profile.*` and `answers.<question id>`. Declare each question in `questions` (`id`, `text`, `options`, default yes/no). While the answer is unknown, Aster asks; the document is never silently optional. "Fresh vs renewal" is the question `route` with options `["fresh", "renewal"]`.
  - `stage`: `apply` (default; only these can block), `institute` or `later` (e.g. after selection).
  - `period` (display text, e.g. "previous academic year") and `holder` (`student` / `parent` / `either`).
- Validate: `cd backend && uv run python -m app.research.packs validate`
