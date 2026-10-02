"""Service-key Supabase client + repositories. The service key bypasses RLS, so every function
takes the user_id from the verified JWT and scopes its query by it."""

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


def update_profile(db: Client, user_id: str, values: Row, source_type: str) -> Row | None:
    """Writes the values and one profile_field_sources row per key (guardrail 2)."""
    if not values:
        return get_profile(db, user_id)
    rows = db.table("profiles").update(values).eq("id", user_id).execute().data
    sources = [
        {"user_id": user_id, "field_key": k, "source_type": source_type, "source_ref": {}}
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


def add_message(db: Client, user_id: str, session_id: str, values: Row) -> Row | None:
    """session_id must come from get_session(db, user_id, ...): the FK alone does not check
    that the session belongs to this user."""
    row = {**values, "user_id": user_id, "session_id": session_id}
    return _one(db.table("messages").insert(row).execute().data)


def list_messages(db: Client, user_id: str, session_id: str, limit: int = 50) -> list[Row]:
    q = db.table("messages").select("*").eq("session_id", session_id).eq("user_id", user_id)
    return q.order("created_at").limit(limit).execute().data


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
