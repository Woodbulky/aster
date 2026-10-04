"""Audit chain verification. The DB trigger (`audit_chain`, migrations 0001/0006) hashes
sha256(prev_hash|actor|action|payload::text|created_at::text) per (session_id, user_id) chain;
this recomputes every hash from the stored columns and checks the links.

    uv run python -m app.audit [--user <uuid>]      # exit 1 if any chain is broken
"""

import argparse
import hashlib
import sys
from collections import defaultdict
from typing import Any

# The hash covers Postgres' text forms, so read them back with the same casts.
COLS = (
    "id,user_id,session_id,actor,action,prev_hash,hash,"
    "payload_text:payload::text,created_text:created_at::text"
)
PAGE = 1000


def row_hash(r: dict[str, Any]) -> str:
    raw = "|".join(
        [r["prev_hash"], r["actor"], r["action"], r.get("payload_text") or "", r["created_text"]]
    )
    return hashlib.sha256(raw.encode()).hexdigest()


def verify_chain(rows: list[dict[str, Any]]) -> list[int]:
    """Ids of rows whose hash or link is wrong. `rows` = one chain, any order."""
    bad, prev = [], "GENESIS"
    for r in sorted(rows, key=lambda r: r["id"]):
        if r["prev_hash"] != prev or r["hash"] != row_hash(r):
            bad.append(r["id"])
        prev = r["hash"]  # keep walking from the stored hash: one edit flags one row, not all after
    return bad


def fetch(db: Any, user_id: str | None = None, session_id: str | None = None) -> list[dict]:
    rows: list[dict] = []
    while True:
        q = db.table("audit_events").select(COLS).order("id").range(len(rows), len(rows) + PAGE - 1)
        if user_id:
            q = q.eq("user_id", user_id)
        if session_id:
            q = q.eq("session_id", session_id)
        page = q.execute().data
        rows += page
        if len(page) < PAGE:
            return rows


def verify_all(rows: list[dict[str, Any]]) -> dict[tuple, list[int]]:
    chains: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        chains[(r["user_id"], r["session_id"])].append(r)
    return {k: verify_chain(v) for k, v in chains.items()}


def main() -> int:
    from app.db.supabase import get_db

    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--user")
    args = p.parse_args()
    rows = fetch(get_db(), user_id=args.user)
    result = verify_all(rows)
    for (uid, sid), bad in sorted(result.items(), key=lambda kv: str(kv[0])):
        n = sum(1 for r in rows if (r["user_id"], r["session_id"]) == (uid, sid))
        status = "ok" if not bad else f"BROKEN at ids {bad}"
        print(f"user {str(uid)[:8]} session {str(sid or 'profile')[:8]:8}  {n:4} events  {status}")
    broken = sum(1 for b in result.values() if b)
    print(f"{len(rows)} events, {len(result)} chains, {broken} broken")
    return 1 if broken else 0


if __name__ == "__main__":
    sys.exit(main())
