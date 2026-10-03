# Knowledge packs

One JSON file per scheme: `knowledge/<portal>/<scheme_slug>.json`, following `knowledge/_TEMPLATE.scheme.json`. Each portal folder has a `_portal.json` (`{name, url}`); `url` becomes the session's `portal_url`.

Current packs (all `draft` until the team verifies them): MahaDBT GOI Post-Matric SC, GOI Post-Matric ST, Shahu Maharaj EBC, Post-Matric OBC, Panjabrao Deshmukh hostel (DHE); LIC Golden Jubilee (general, 2026); NSP Central Sector Scheme (CSSS).

Rules:
- Every criterion, document, and deadline needs `source.url` (official site/GR PDF) and `source.quote`, copied verbatim (Marathi is fine).
- `status: "draft"` until a team member has opened every URL and checked every quote and value. Then set `"verified"`, `verified_by`, `verified_on`.
- `logic` is JSON Logic over `profile.<profiles column>` (see docs/RESEARCH.md for the operators). If a criterion can't be expressed, leave `logic: null` → it evaluates to `unknown` and Aster asks or explains.
- Never invent limits, amounts, deadlines or document names. Missing info goes in `notes`.
- Validate: `cd backend && uv run python -m app.research.packs validate`
