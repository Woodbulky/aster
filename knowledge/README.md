# Knowledge packs

One JSON file per scheme: `knowledge/<portal>/<scheme_slug>.json`, following `knowledge/mahadbt/_TEMPLATE.scheme.json`.

Rules:
- Every criterion, document, and deadline needs `source.url` (official site/GR PDF) and `source.quote`, copied verbatim (Marathi is fine).
- `status: "draft"` until a team member has opened every URL and checked every quote and value. Then set `"verified"`, `verified_by`, `verified_on`.
- `logic` is JSON Logic over `profile.*` and `computed.*`. If a criterion can't be expressed, leave `logic: null` → it evaluates to `unknown` and Aster asks or explains.
- Never invent limits, amounts, deadlines or document names. Missing info goes in `notes`.
- Validate: `cd backend && uv run python -m app.research.packs validate`
