---
description: Implement a Aster build milestone, e.g. /milestone M3
---
Implement milestone $ARGUMENTS of Aster.

1. Read CLAUDE.md, then the "$ARGUMENTS" section of docs/BUILD_PLAN.md, then every doc listed under its **Read:** line. Check docs/PROGRESS.md for open issues from earlier milestones.
2. Reply with a plan: files to create/change, vendor docs you will fetch, schema changes (migration file names), and how you will verify EACH acceptance criterion. Then STOP and wait for my OK.
3. After my OK, implement in small steps. Schema changes: write supabase/migrations/NNNN_*.sql, then apply with the Supabase MCP apply_migration tool, then regenerate TS types.
4. Run backend tests + ruff, web lint + typecheck + build. Fix failures.
5. Verify every acceptance criterion and show the evidence (command output, SQL results, or exact manual steps for me to click through).
6. Run /guardrails on your changes.
7. Tick the milestone box in docs/BUILD_PLAN.md, append to docs/PROGRESS.md, and propose a commit message.
