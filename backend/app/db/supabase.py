"""Service-key Supabase client + repositories. The service key bypasses RLS, so every function
takes the user_id from the verified JWT and scopes its query by it."""

import json
import re
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any

from supabase import Client, create_client

from app.config import get_settings

Row = dict[str, Any]


@lru_cache
def get_db() -> Client:
    s = get_settings()
    return create_client(s.supabase_url, s.supabase_secret_key)


def _one(rows: list[Any]) -> Row | None:
    return rows[0] if rows else None


# ---------- profile ----------
def get_profile(db: Client, user_id: str) -> Row | None:
    return _one(db.table("profiles").select("*").eq("id", user_id).limit(1).execute().data)


def update_profile(
    db: Client, user_id: str, values: Row, source_type: str, source_ref: Row | None = None
) -> Row | None:
    """Writes the values and one profile_field_sources row per key (guardrail 2)."""
    if not values:
        return get_profile(db, user_id)
    rows = db.table("profiles").update(values).eq("id", user_id).execute().data
    now = datetime.now(UTC).isoformat()
    sources = [
        {
            "user_id": user_id,
            "field_key": k,
            "source_type": source_type,
            "source_ref": source_ref or {},
            "confirmed_at": now,  # the column default only applies on insert, not on upsert
        }
        for k in values
    ]
    db.table("profile_field_sources").upsert(sources).execute()
    return _one(rows)


# ---------- assistant ----------
def get_assistant(db: Client, user_id: str) -> Row | None:
    q = db.table("assistant_settings").select("*").eq("user_id", user_id).limit(1)
    return _one(q.execute().data)


def upsert_assistant(db: Client, user_id: str, values: Row) -> Row | None:
    rows = db.table("assistant_settings").upsert({**values, "user_id": user_id}).execute().data
    return _one(rows)


# ---------- sessions & messages ----------
def create_session(db: Client, user_id: str, values: Row) -> Row | None:
    return _one(db.table("form_sessions").insert({**values, "user_id": user_id}).execute().data)


def get_session(db: Client, user_id: str, session_id: str) -> Row | None:
    q = db.table("form_sessions").select("*").eq("id", session_id).eq("user_id", user_id)
    return _one(q.limit(1).execute().data)


def update_session(db: Client, user_id: str, session_id: str, values: Row) -> Row | None:
    q = db.table("form_sessions").update(values).eq("id", session_id).eq("user_id", user_id)
    return _one(q.execute().data)


# 12-digit Aadhaar (optionally grouped 4-4-4) or an 11-18 digit run (bank account). \d also
# matches Devanagari digits. ponytail: 9-10 digit bank accounts pass (they look like mobiles).
_ID_NUMBER = re.compile(r"(?<!\d)(?:\d{4}[ -]?\d{4}[ -]?\d{4}|\d{11,18})(?!\d)")


def redact_ids(text: str) -> str:
    """Guardrail 6: keep only the last 4 digits of an Aadhaar/bank-like number."""
    return _ID_NUMBER.sub(lambda m: f"[number ending {m.group()[-4:]}]", text)


def add_message(db: Client, user_id: str, session_id: str, values: Row) -> Row | None:
    """session_id must come from get_session(db, user_id, ...): the FK alone does not check
    that the session belongs to this user. Content and tool payloads are redacted here, the one
    place every message is written (the LLM reads history back from these rows)."""
    values = dict(values)
    if values.get("content"):
        values["content"] = redact_ids(values["content"])
    if values.get("tool_payload") is not None:
        raw = json.dumps(values["tool_payload"], ensure_ascii=False, default=str)
        values["tool_payload"] = json.loads(redact_ids(raw))
    row = {**values, "user_id": user_id, "session_id": session_id}
    return _one(db.table("messages").insert(row).execute().data)


def list_messages(db: Client, user_id: str, session_id: str, limit: int = 50) -> list[Row]:
    """The latest `limit` messages, oldest first."""
    q = db.table("messages").select("*").eq("session_id", session_id).eq("user_id", user_id)
    return q.order("created_at", desc=True).limit(limit).execute().data[::-1]


# ---------- profile proposals (guardrail 4: nothing is saved until the user confirms) ----------
def create_proposal(db: Client, user_id: str, values: Row) -> Row | None:
    row = {**values, "user_id": user_id}
    return _one(db.table("profile_proposals").insert(row).execute().data)


def get_pending_proposal(db: Client, user_id: str, proposal_id: str) -> Row | None:
    q = db.table("profile_proposals").select("*").eq("id", proposal_id).eq("user_id", user_id)
    return _one(q.eq("status", "pending").limit(1).execute().data)


def latest_pending_proposal(db: Client, user_id: str, session_id: str) -> Row | None:
    q = db.table("profile_proposals").select("*").eq("user_id", user_id)
    q = q.eq("session_id", session_id).eq("status", "pending")
    return _one(q.order("created_at", desc=True).limit(1).execute().data)


def set_proposal_status(db: Client, user_id: str, proposal_id: str, status: str) -> None:
    q = db.table("profile_proposals").update({"status": status}).eq("id", proposal_id)
    q.eq("user_id", user_id).eq("status", "pending").execute()


# ---------- audit ----------
def write_audit(
    db: Client,
    user_id: str,
    session_id: str | None,
    action: str,
    payload: Row,
    actor: str = "system",
) -> None:
    row = {
        "user_id": user_id,
        "session_id": session_id,
        "actor": actor,
        "action": action,
        "payload": payload,
    }
    db.table("audit_events").insert(row).execute()
