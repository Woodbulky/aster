---
description: Review current changes against Aster product guardrails and security rules
---
Review the uncommitted diff (git diff + new files) against the "Product guardrails" and "Supabase rules" in CLAUDE.md.
For each guardrail, answer PASS / FAIL / N/A with file:line evidence. Specifically check:
- service/secret keys or GATEWAY_TOKEN never reach web/ code or logs
- every backend query is scoped by the verified user_id
- no screen frames, audio, full Aadhaar or bank account numbers are persisted or logged
- profile writes only through confirmed proposals
- LLM outputs that become field values pass the validator
- OTP/password/captcha/submit handling follows docs/FORM_FILL.md
- new tables have RLS enabled + policies
Fix any FAIL before finishing.
