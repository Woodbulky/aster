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


# A certificate's own number ("क्रमांक: 42031458382" on an income certificate) is not an Aadhaar or
# bank number: masking it made extraction pick another number (seen live). "मांक": PDF text layers
# drop the "क्र" conjunct. Aadhaar-sized (12 digits) or near an Aadhaar/bank word stays masked.
_CERT_LABEL = re.compile(
    r"(?:मांक|certificate\s*(?:no|number)|cert\s*(?:no|number))[^\d\n]{0,20}$", re.I
)
_ID_WORDS = re.compile(r"aadha+r|आधार|uid|account|a/c|खाते|खाता|बँक|बैंक|bank", re.I)


def _is_id(text: str, m: re.Match[str], above: str = "") -> bool:
    """above: the line before, for OCR that puts the label on its own line (seen live: "क्रमांक",
    then the number)."""
    if len(re.sub(r"\D", "", m.group())) == 12:
        return True
    before = f"{above} {text[: m.start()]}"[-40:]
    return not _CERT_LABEL.search(before) or bool(_ID_WORDS.search(before))


def id_numbers(text: str, above: str = "") -> list[re.Match[str]]:
    """The Aadhaar/bank-like numbers in text (guardrail 6), not a labelled certificate number."""
    return [m for m in _ID_NUMBER.finditer(text) if _is_id(text, m, above)]


def redact_ids(text: str, above: str = "") -> str:
    """Guardrail 6: keep only the last 4 digits of an Aadhaar/bank-like number."""
    return _ID_NUMBER.sub(
        lambda m: f"[number ending {m.group()[-4:]}]" if _is_id(text, m, above) else m.group(),
        text,
    )


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


def proposal_for_flag(db: Client, user_id: str, flag_id: str) -> Row | None:
    """The profile proposal already made from this flag's resolution, if any."""
    q = db.table("profile_proposals").select("id").eq("user_id", user_id)
    return _one(q.eq("source_ref->>flag_id", flag_id).limit(1).execute().data)


def set_proposal_status(db: Client, user_id: str, proposal_id: str, status: str) -> None:
    q = db.table("profile_proposals").update({"status": status}).eq("id", proposal_id)
    q.eq("user_id", user_id).eq("status", "pending").execute()


# ---------- research ----------
def add_fetched(db: Client, user_id: str, session_id: str, values: Row) -> Row | None:
    row = {**values, "user_id": user_id, "session_id": session_id}
    return _one(db.table("fetched_content").insert(row).execute().data)


def get_fetched(db: Client, user_id: str, session_id: str, content_id: str) -> Row | None:
    q = db.table("fetched_content").select("*").eq("id", content_id).eq("user_id", user_id)
    return _one(q.eq("session_id", session_id).limit(1).execute().data)


def find_fetched(db: Client, user_id: str, session_id: str, url: str) -> Row | None:
    q = db.table("fetched_content").select("*").eq("url", url).eq("user_id", user_id)
    q = q.eq("session_id", session_id).order("fetched_at", desc=True).limit(1)
    return _one(q.execute().data)


def list_fetched(db: Client, user_id: str, session_id: str) -> list[Row]:
    """This session's stored pages: url + content id only (the text stays in the table)."""
    q = db.table("fetched_content").select("id,url").eq("user_id", user_id)
    return q.eq("session_id", session_id).order("fetched_at").execute().data


# ---------- research shared across students (public web facts, no user data) ----------
def fresh_research_cache(db: Client) -> list[Row]:
    """Unexpired rows. ponytail: the whole (small) table; an index on a trigram if it grows."""
    now = datetime.now(UTC).isoformat()
    return db.table("research_cache").select("*").gt("expires_at", now).execute().data


def put_research_cache(db: Client, values: Row) -> None:
    db.table("research_cache").upsert(values, on_conflict="scheme_norm").execute()


def add_research(db: Client, user_id: str, session_id: str, values: Row) -> Row | None:
    row = {**values, "user_id": user_id, "session_id": session_id}
    return _one(db.table("research_results").insert(row).execute().data)


def latest_research(
    db: Client, user_id: str, session_id: str, scheme: str, kind: str | None = None
) -> Row | None:
    q = db.table("research_results").select("*").eq("session_id", session_id)
    q = q.eq("user_id", user_id).eq("scheme", scheme)
    if kind:
        q = q.eq("kind", kind)
    return _one(q.order("created_at", desc=True).limit(1).execute().data)


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


# ---------- documents & fields (M6) ----------
BUCKET = "documents"


def add_document(db: Client, user_id: str, session_id: str, values: Row) -> Row | None:
    row = {**values, "user_id": user_id, "session_id": session_id}
    return _one(db.table("documents").insert(row).execute().data)


def get_document(db: Client, user_id: str, document_id: str) -> Row | None:
    q = db.table("documents").select("*").eq("id", document_id).eq("user_id", user_id)
    return _one(q.limit(1).execute().data)


def update_document(db: Client, user_id: str, document_id: str, values: Row) -> None:
    db.table("documents").update(values).eq("id", document_id).eq("user_id", user_id).execute()


def latest_read_document(db: Client, user_id: str, doc_type: str, not_session: str) -> Row | None:
    """The newest document of this type read in another of the user's applications."""
    q = (
        db.table("documents")
        .select("storage_path,mime")
        .eq("user_id", user_id)
        .eq("doc_type", doc_type)
        .eq("status", "extracted")
        .neq("session_id", not_session)
    )
    return _one(q.order("created_at", desc=True).limit(1).execute().data)


def list_documents(db: Client, user_id: str, session_id: str, full: bool = False) -> list[Row]:
    """Oldest first. full=True adds the OCR json (pages + lines)."""
    cols = "id,doc_type,requirement_id,status,error,created_at,page_count"
    cols += ",ocr" if full else ""
    q = db.table("documents").select(cols)
    return q.eq("session_id", session_id).eq("user_id", user_id).order("created_at").execute().data


def storage_exists(db: Client, user_id: str, folder: str, name: str) -> bool:
    """folder must start with the user's own id (storage RLS layout)."""
    assert folder.startswith(f"{user_id}/")
    files = db.storage.from_(BUCKET).list(folder, {"search": name})
    return any(f.get("name") == name for f in files)


def add_field_value(db: Client, user_id: str, session_id: str, values: Row) -> Row | None:
    """Guardrail 2, in code: no source, no value."""
    if not values.get("source_type") or not values.get("source_ref"):
        raise ValueError("a field value needs source_type and source_ref")
    row = {**values, "user_id": user_id, "session_id": session_id}
    return _one(db.table("field_values").insert(row).execute().data)


def list_field_values(db: Client, user_id: str, session_id: str) -> list[Row]:
    q = db.table("field_values").select("*").eq("session_id", session_id).eq("user_id", user_id)
    return q.order("created_at").execute().data


def add_flag(db: Client, user_id: str, session_id: str, values: Row) -> Row | None:
    row = {**values, "user_id": user_id, "session_id": session_id}
    return _one(db.table("flags").insert(row).execute().data)


def get_flag(db: Client, user_id: str, flag_id: str) -> Row | None:
    q = db.table("flags").select("*").eq("id", flag_id).eq("user_id", user_id)
    return _one(q.limit(1).execute().data)


def list_profile_sources(db: Client, user_id: str) -> list[Row]:
    return db.table("profile_field_sources").select("*").eq("user_id", user_id).execute().data


def shown_flag_ids(db: Client, user_id: str, session_id: str) -> set[str]:
    """Flags whose card was already sent (ask_resolution tool rows)."""
    q = db.table("messages").select("tool_payload").eq("session_id", session_id)
    rows = q.eq("user_id", user_id).eq("tool_name", "ask_resolution").execute().data
    out = set()
    for r in rows:
        args = (r.get("tool_payload") or {}).get("args") or "{}"
        try:
            out.add(
                json.loads(args).get("flag_id") if isinstance(args, str) else args.get("flag_id")
            )
        except (ValueError, AttributeError):
            continue
    return out


def update_flag(db: Client, user_id: str, flag_id: str, values: Row) -> None:
    db.table("flags").update(values).eq("id", flag_id).eq("user_id", user_id).execute()


def list_flags(db: Client, user_id: str, session_id: str, status: str | None = None) -> list[Row]:
    q = db.table("flags").select("*").eq("session_id", session_id).eq("user_id", user_id)
    if status:
        q = q.eq("status", status)
    return q.order("created_at").execute().data


def add_rule_evaluations(db: Client, user_id: str, session_id: str, rows: list[Row]) -> None:
    if rows:
        full = [{**r, "user_id": user_id, "session_id": session_id} for r in rows]
        db.table("rule_evaluations").insert(full).execute()


# ---------- consents & account (M8) ----------
def latest_consent(db: Client, user_id: str, scope: str) -> Row | None:
    q = db.table("consents").select("*").eq("user_id", user_id).eq("scope", scope)
    return _one(q.order("created_at", desc=True).limit(1).execute().data)


def add_consent(db: Client, user_id: str, values: Row) -> Row | None:
    return _one(db.table("consents").insert({**values, "user_id": user_id}).execute().data)


def delete_user(db: Client, user_id: str) -> int:
    """Every Storage object under <uid>/, then the auth user: every table cascades from
    auth.users. -> number of objects removed."""
    bucket = db.storage.from_(BUCKET)
    removed = 0
    for _ in range(100):  # list_v2 without a delimiter lists the whole tree under the prefix
        page = bucket.list_v2({"prefix": f"{user_id}/", "with_delimiter": False, "limit": 1000})
        names = [o.name for o in page.objects if o.name.startswith(f"{user_id}/")]
        if not names:
            break
        bucket.remove(names)
        removed += len(names)
    else:  # a remove that silently does nothing: never delete the account with files left
        raise RuntimeError("storage objects could not be removed")
    db.auth.admin.delete_user(user_id)
    return removed
