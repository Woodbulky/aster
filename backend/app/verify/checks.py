"""Verification across sources (VERIFICATION.md step 8): profile candidates, contradictions, rules,
missing documents -> flags; and the user's resolution of a flag (guardrail 3: the user picks, with a
reason; candidates are never edited or deleted)."""

from datetime import UTC, date, datetime
from functools import cache
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, field_validator
from supabase import Client

from app.db import supabase as repo
from app.research.packs import usable_packs
from app.verify import names
from app.verify.contradictions import best, canon, disagreements, effective, name_match_min, same
from app.verify.extraction import DOC_LABELS, field_label
from app.verify.rules_engine import evaluate, variables
from app.verify.validator import KIND, parse_date

Row = dict[str, Any]
RULES_DIR = Path(__file__).parent / "rules"
FACT_PREFIXES = ("fields.", "docs.", "computed.", "pack.")
# Profile columns that are also canonical field keys: confirmed profile values are candidates.
PROFILE_KEYS = (
    "full_name",
    "dob",
    "gender",
    "category",
    "caste",
    "annual_family_income",
    "domicile_state",
    "district",
    "ssc_board",
    "ssc_year",
    "ssc_percentage",
    "hsc_board",
    "hsc_year",
    "hsc_percentage",
    "current_course",
    "current_year",
    "institute_name",
    "aadhaar_last4",
)
SOURCE_LABEL = {
    "profile": "Your profile",
    "voice": "You said",
    "text": "You typed",
    "resolution": "Your earlier choice",
    "aadhaar_qr": "Aadhaar QR",
}
MESSAGES = {
    "contradiction": {
        "en": "These don't match. Pick the right value and say why.",
        "hi": "ये मेल नहीं खाते। सही मान चुनें और कारण बताएँ।",
        "mr": "हे जुळत नाहीत. योग्य माहिती निवडा आणि कारण सांगा.",
    },
    "missing_doc": {
        "en": "This required document is not uploaded yet.",
        "hi": "यह ज़रूरी दस्तावेज़ अभी अपलोड नहीं हुआ है।",
        "mr": "हे आवश्यक कागदपत्र अजून अपलोड झालेले नाही.",
    },
    "low_confidence": {
        "en": "This value was hard to read. Check it against your document.",
        "hi": "यह जानकारी ठीक से पढ़ी नहीं जा सकी। अपने दस्तावेज़ से मिलाकर देखें।",
        "mr": "ही माहिती नीट वाचता आली नाही. तुमच्या कागदपत्राशी जुळवून पाहा.",
    },
}
LOW_CONFIDENCE = 0.6
# Fields worth a "hard to read, please check" card. Board/institute/course text is not.
CHECKED_FIELDS = {
    "full_name",
    "father_name",
    "mother_name",
    "dob",
    "gender",
    "category",
    "caste",
    "annual_family_income",
    "income_cert_issue_date",
    "income_cert_fy",
    "ssc_year",
    "ssc_percentage",
    "hsc_year",
    "hsc_percentage",
    "aadhaar_last4",
    "account_holder_name",
    "bank_ifsc",
    "bank_account_last4",
    "domicile_state",
}


def _unsure(r: Row) -> bool:
    return r["source_type"] == "document" and (r.get("confidence") or 0) < LOW_CONFIDENCE


class Rule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    severity: Literal["block", "warn"]
    reason_code: str
    field_key: str
    logic: dict[str, Any]
    message: dict[Literal["en", "hi", "mr"], str]

    @field_validator("logic")
    @classmethod
    def _vars(cls, v: dict[str, Any]) -> dict[str, Any]:
        bad = [x for x in variables(v) if not x.startswith(FACT_PREFIXES)]
        if bad:
            raise ValueError(f"unknown facts {bad}; use {FACT_PREFIXES}")
        return v


class RuleSet(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ruleset: str
    version: str
    rules: list[Rule]


@cache
def rulesets() -> tuple[RuleSet, ...]:
    files = sorted(RULES_DIR.glob("*.json"))
    return tuple(RuleSet.model_validate_json(f.read_text(encoding="utf-8")) for f in files)


def _display(field_key: str, v: Any) -> str:
    if KIND.get(field_key) in ("amount", "percent", "year"):
        return canon(field_key, v)  # numeric 120000.0 -> "120000"
    return str(v)


def sync_profile_candidates(db: Client, user_id: str, session_id: str, rows: list[Row]) -> None:
    """Add the confirmed profile values as candidates (once per distinct value)."""
    profile = repo.get_profile(db, user_id) or {}
    sources = {s["field_key"]: s for s in repo.list_profile_sources(db, user_id)}
    for k in PROFILE_KEYS:
        v = profile.get(k)
        if v in (None, ""):
            continue
        mine = [r for r in rows if r["source_type"] == "profile" and r["field_key"] == k]
        if mine and same(k, mine[-1]["value"], v):
            continue
        src = sources.get(k, {})
        row = repo.add_field_value(
            db,
            user_id,
            session_id,
            {
                "field_key": k,
                "value": _display(k, v),
                "value_normalized": canon(k, v),
                "source_type": "profile",
                "source_ref": {
                    "profile_field": k,
                    "confirmed_via": src.get("source_type", "manual"),
                    "confirmed_at": src.get("confirmed_at"),
                },
                "confidence": 1.0,
                "status": "candidate",
            },
        )
        if row:
            rows.append(row)


def _live_docs(docs: list[Row], just_read: str | None = None) -> dict[str, Row]:
    """Latest read document per type (a replacement supersedes the earlier upload). just_read: the
    document the pipeline is finishing (its status flips to extracted after the checks)."""
    out: dict[str, Row] = {}
    for d in docs:
        if d["status"] == "extracted" or d["id"] == just_read:
            out[d["doc_type"]] = d
    return out


def candidate_view(r: Row, docs: dict[str, Row]) -> Row:
    ref = r.get("source_ref") or {}
    doc = docs.get(ref.get("document_id") or "")
    if r["source_type"] == "document":
        doc_label = DOC_LABELS.get(ref.get("doc_type", ""), "Document")
        label = f"{doc_label} · {', '.join(ref.get('line_ids', []))}"
    else:
        label = SOURCE_LABEL.get(r["source_type"], r["source_type"])
    pages = ((doc or {}).get("ocr") or {}).get("pages") or []
    page = ref.get("page")
    return {
        "id": r["id"],
        "field_key": r["field_key"],
        "value": r["value"],
        "source_type": r["source_type"],
        "label": label,
        "document_id": ref.get("document_id"),
        "page": pages[page] if isinstance(page, int) and page < len(pages) else None,
        "bbox": ref.get("bbox") or [],
        "confidence": r.get("confidence"),
    }


def facts(eff: dict[str, list[Row]], live: dict[str, Row], pack: Any) -> Row:
    fields = {k: b["value"] for k, rows in eff.items() if (b := best(rows))}
    computed: Row = {}
    if (nm := name_match_min(eff.get("full_name", []))) is not None:
        computed["name_match_min"] = nm
    holder, me = best(eff.get("account_holder_name", [])), best(eff.get("full_name", []))
    if holder and me:
        computed["bank_holder_match"] = names.score(holder["value"], me["value"])
    if issued := parse_date(fields.get("income_cert_issue_date", "")):
        computed["income_cert_age_days"] = (date.today() - issued).days
    return {
        "fields": fields,
        "docs": {t: {"present": True} for t in live},
        "computed": computed,
        "pack": (pack.computed_facts if pack else {}),
    }


def _lookup(path: str, data: Row) -> Any:
    cur: Any = data
    for part in path.split("."):
        cur = cur.get(part) if isinstance(cur, dict) else None
    return cur


def _signature(flag: Row) -> list[str]:
    return sorted(
        {canon(c["field_key"], c["value"]) for c in flag["details"].get("candidates", [])}
    )


def _save_flag(db: Client, uid: str, sid: str, existing: list[Row], flag: Row) -> Row | None:
    """Insert unless the same problem is already open (then refresh it) or was already answered
    for the same values. Values, not row ids: the user's own answer adds a confirmed row with the
    same value, and comparing ids re-raised the flag they had just answered (seen live).
    -> the new flag, or None."""
    key = (flag["type"], flag["reason_code"], flag.get("field_key"))
    sig = _signature(flag)
    same_key = [f for f in existing if (f["type"], f["reason_code"], f.get("field_key")) == key]
    for f in same_key:
        if f["status"] == "open":
            if f["details"] != flag["details"] or f["severity"] != flag["severity"]:
                repo.update_flag(
                    db, uid, f["id"], {"details": flag["details"], "severity": flag["severity"]}
                )
            return None
    if any(_signature(f) == sig for f in same_key):
        return None
    row = repo.add_flag(db, uid, sid, flag)
    if row:
        existing.append(row)
    return row


def _load(
    db: Client, user_id: str, sid: str, just_read: str | None = None
) -> tuple[dict[str, Row], dict[str, Row], dict[str, list[Row]], dict[str, list[Row]]]:
    """-> (live docs by type, docs by id, effective candidates, firm candidates)."""
    rows = repo.list_field_values(db, user_id, sid)
    sync_profile_candidates(db, user_id, sid, rows)
    docs = repo.list_documents(db, user_id, sid, full=True)
    live = _live_docs(docs, just_read)
    eff = effective(rows, {d["id"] for d in live.values()})
    # A hard-to-read value gets its own low_confidence flag and stays out of the comparisons until
    # the user confirms it (seen live: "9310" read as gender, the Aadhaar header as the name).
    firm = {k: [r for r in rs if not _unsure(r)] for k, rs in eff.items()}
    return live, {d["id"]: d for d in docs}, eff, firm


def readiness(db: Client, user_id: str, session: Row) -> Row:
    """The readiness card: every value the form will use, with its source, and what still blocks.
    Ready = no open blocking flag (acknowledged ones are listed with the user's reason)."""
    live, by_id, _, firm = _load(db, user_id, session["id"])
    flags = repo.list_flags(db, user_id, session["id"])
    open_ = [f for f in flags if f["status"] == "open"]
    fields = []
    for key in sorted(firm, key=field_label):
        if b := best(firm[key]):
            v = candidate_view(b, by_id)
            fields.append(
                {
                    "field_key": key,
                    "label": field_label(key),
                    "value": b["value"],
                    "source": v["label"],
                    "confirmed": b["status"] == "confirmed",
                }
            )
    return {
        "session_id": session["id"],
        "ready": not any(f["severity"] == "block" for f in open_),
        "open_block": [flag_summary(f) for f in open_ if f["severity"] == "block"],
        "open_warn": [flag_summary(f) for f in open_ if f["severity"] == "warn"],
        "acknowledged": [
            flag_summary(f) | {"reason": (f.get("resolution") or {}).get("reason")}
            for f in flags
            if f["status"] == "acknowledged"
        ],
        "documents": [DOC_LABELS.get(t, t) for t in live],
        "fields": fields,
        "note": "Aster checked your documents against each other. The scheme authority makes the "
        "final decision; you review and submit the form yourself.",
    }


def run_checks(
    db: Client, user_id: str, session: Row, *, include_missing: bool, just_read: str | None = None
) -> list[Row]:
    """-> flags created by this run. include_missing: also flag required documents not uploaded
    (only when the user says they're done, not after every upload)."""
    sid = session["id"]
    live, by_id, eff, firm = _load(db, user_id, sid, just_read)
    pack = usable_packs().get(session.get("scheme_key") or "")
    existing = repo.list_flags(db, user_id, sid)
    new: list[Row] = []

    def save(flag: Row) -> None:
        if row := _save_flag(db, user_id, sid, existing, flag):
            new.append(row)

    for d in disagreements(firm):
        cands = [candidate_view(r, by_id) for r in d.candidates]
        save(
            {
                "type": "contradiction",
                "severity": d.severity,
                "field_key": d.field_key,
                "reason_code": "value_mismatch",
                "details": {
                    "field_label": field_label(d.field_key),
                    "message": MESSAGES["contradiction"],
                    "candidates": cands,
                    "candidate_ids": [c["id"] for c in cands],
                },
            }
        )

    for key, rs in eff.items():
        if key not in CHECKED_FIELDS:
            continue
        for r in rs:
            if _unsure(r):
                c = candidate_view(r, by_id)
                save(
                    {
                        "type": "low_confidence",
                        "severity": "warn",
                        "field_key": key,
                        "reason_code": "low_confidence",
                        "details": {
                            "field_label": field_label(key),
                            "message": MESSAGES["low_confidence"],
                            "candidates": [c],
                            "candidate_ids": [c["id"]],
                        },
                    }
                )

    data = facts(firm, live, pack)
    evals = []
    for rs in rulesets():
        for rule in rs.rules:
            status, missing = evaluate(rule.logic, data)
            inputs = {v: _lookup(v, data) for v in sorted(variables(rule.logic))}
            evals.append(
                {
                    "rule_id": rule.id,
                    "rule_version": rs.version,
                    "inputs": {**inputs, "missing": missing},
                    "result": status == "met",
                }
            )
            if status != "met":
                continue
            related = firm.get(rule.field_key, [])
            if rule.field_key == "account_holder_name" and (me := best(firm.get("full_name", []))):
                related = [*related, me]
            cands = [candidate_view(r, by_id) for r in related]
            save(
                {
                    "type": "rule",
                    "severity": rule.severity,
                    "field_key": rule.field_key,
                    "reason_code": rule.reason_code,
                    "details": {
                        "rule_id": rule.id,
                        "rule_version": rs.version,
                        "field_label": field_label(rule.field_key),
                        "message": rule.message,
                        "inputs": inputs,
                        "candidates": cands,
                        "candidate_ids": [c["id"] for c in cands],
                    },
                }
            )
    repo.add_rule_evaluations(db, user_id, sid, evals)

    required = {d.doc_type: d for d in (pack.documents if pack else []) if d.required}
    for f in existing:  # an uploaded document closes its missing-document flag (logged)
        if f["type"] == "missing_doc" and f["status"] == "open" and f["field_key"] in live:
            resolution = {"by": "system", "reason": "document uploaded"}
            repo.update_flag(db, user_id, f["id"], {"status": "resolved", "resolution": resolution})
            f["status"] = "resolved"
            repo.write_audit(
                db, user_id, sid, "flag.resolved", {"flag_id": f["id"], "by": "system"}
            )
    if include_missing:
        for t, doc in required.items():
            if t == "other" or doc.required_if or t in live:
                continue
            save(
                {
                    "type": "missing_doc",
                    "severity": "block",
                    "field_key": t,
                    "reason_code": "required_doc_missing",
                    "details": {
                        "label": DOC_LABELS.get(t, t),
                        "message": MESSAGES["missing_doc"],
                        "source": doc.source.model_dump(),
                        "candidate_ids": [],
                    },
                }
            )
    for f in new:
        payload = {"flag_id": f["id"], "type": f["type"], "reason_code": f["reason_code"]}
        repo.write_audit(
            db, user_id, sid, "flag.raised", payload | {"field_key": f.get("field_key")}
        )
    return new


class ResolveError(ValueError):
    pass


def resolve(
    db: Client,
    user_id: str,
    session_id: str,
    flag_id: str,
    *,
    reason: str,
    via: Literal["tap", "voice"],
    candidate_id: str | None = None,
    value: str | None = None,
    message_id: str | None = None,
) -> Row:
    """The user's answer to a flag. A pick or a typed value -> a confirmed field_values row that
    points at the evidence; neither -> acknowledged. Raises ResolveError."""
    flag = repo.get_flag(db, user_id, flag_id)
    if not flag or flag["session_id"] != session_id:
        raise ResolveError("no such flag in this session")
    if flag["status"] != "open":
        raise ResolveError(f"flag is already {flag['status']}")
    reason = reason.strip()
    if len(reason) < 3:
        raise ResolveError("a reason is required")
    if candidate_id and value:
        raise ResolveError("pick a candidate or type a value, not both")
    cands = {c["id"]: c for c in flag["details"].get("candidates", [])}
    if candidate_id and candidate_id not in cands:
        raise ResolveError("that value is not one of this flag's candidates")
    if value is not None and not value.strip():
        raise ResolveError("the typed value is empty")
    if flag["type"] == "missing_doc" and (candidate_id or value):
        raise ResolveError("a missing document can only be acknowledged")

    evidence = {"via": via, "message_id": message_id}
    resolution: Row = {"reason": reason, **evidence}
    status = "acknowledged"
    if candidate_id or value:
        chosen = cands[candidate_id] if candidate_id else None
        field_key = chosen["field_key"] if chosen else flag["field_key"]
        final = chosen["value"] if chosen else value.strip()  # type: ignore[union-attr]
        row = repo.add_field_value(
            db,
            user_id,
            session_id,
            {
                "field_key": field_key,
                "value": final,
                "value_normalized": canon(field_key, final),
                "source_type": "resolution",
                "source_ref": {"flag_id": flag_id, "candidate_id": candidate_id, **evidence},
                "confidence": 1.0,
                "status": "confirmed",
                "resolves_flag_id": flag_id,
                "resolution_reason": reason,
            },
        )
        resolution |= {
            "candidate_id": candidate_id,
            "field_value_id": (row or {}).get("id"),
            "value": final,  # the card shows what was chosen (a typed value is not a candidate)
        }
        status = "resolved"
    repo.update_flag(
        db,
        user_id,
        flag_id,
        {"status": status, "resolution": resolution, "resolved_at": datetime.now(UTC).isoformat()},
    )
    audit = {"flag_id": flag_id, "field_key": flag.get("field_key"), "via": via}
    repo.write_audit(db, user_id, session_id, f"flag.{status}", audit, "user")
    return {**flag, "status": status, "resolution": resolution}


def propose_profile_update(db: Client, user_id: str, flag: Row) -> Row | None:
    """A resolved flag on a profile field whose final value differs from the saved profile ->
    a pending profile proposal (guardrail 4: the profile changes only after the user confirms the
    card). None when there is nothing to change or the value doesn't fit the profile column."""
    from pydantic import ValidationError

    from app.api.me import ProfileIn

    res = flag.get("resolution") or {}
    if flag.get("status") != "resolved" or not res.get("field_value_id"):
        return None
    if repo.proposal_for_flag(db, user_id, flag["id"]):  # a resent flag_resolved event
        return None
    cand = next(
        (c for c in flag["details"].get("candidates", []) if c["id"] == res.get("candidate_id")),
        None,
    )
    key = cand["field_key"] if cand else flag.get("field_key")
    if key not in PROFILE_KEYS:
        return None
    current = (repo.get_profile(db, user_id) or {}).get(key)
    if current not in (None, "") and same(key, current, res["value"]):
        return None
    value = res["value"] if KIND.get(key, "text") in ("text", "name") else canon(key, res["value"])
    try:
        updates = ProfileIn.model_validate({key: value}).model_dump(mode="json", exclude_none=True)
    except ValidationError:
        return None
    if cand and cand.get("source_type") == "document":
        evidence = "document"
    else:
        evidence = "voice" if res.get("via") == "voice" else "text"
    return repo.create_proposal(
        db,
        user_id,
        {
            "session_id": flag["session_id"],
            "updates": updates,
            "evidence": evidence,
            "message_id": res.get("message_id"),
            "source_ref": {"flag_id": flag["id"], "field_value_id": res["field_value_id"]},
        },
    )


def flag_card(flag: Row, lang: str) -> tuple[str, Row]:
    """-> (card kind, payload). One FlagCard renders every kind."""
    kind = {
        "contradiction": "contradiction",
        "rule": "contradiction",
        "missing_doc": "missing_item",
        "low_confidence": "low_confidence",
    }[flag["type"]]
    d = flag["details"]
    msg = d.get("message") or {}
    cands = d.get("candidates", [])
    pickable = flag["type"] in ("contradiction", "low_confidence") or (
        flag["type"] == "rule" and flag["field_key"] == "full_name"
    )
    # A rule on a single value (12th year not after 10th) is fixed by typing the right value;
    # name rules are answered by picking a spelling (the bank holder rule is acknowledged).
    typeable = flag["type"] in ("contradiction", "low_confidence") or (
        flag["type"] == "rule" and KIND.get(flag["field_key"] or "") != "name"
    )
    return kind, {
        "flag_id": flag["id"],
        "session_id": flag["session_id"],
        "type": flag["type"],
        "severity": flag["severity"],
        "field_key": flag.get("field_key"),
        "field_label": d.get("field_label") or d.get("label"),
        "message": msg.get(lang) or msg.get("en", ""),
        "candidates": cands,
        "can_pick": pickable and bool(cands),
        "can_type": typeable,
        "doc": {"doc_type": flag["field_key"], "label": d.get("label"), "source": d.get("source")}
        if flag["type"] == "missing_doc"
        else None,
        "status": flag["status"],
    }


def flag_summary(flag: Row) -> Row:
    """What the LLM sees: no candidate ids it could misuse, values only for its sentence."""
    d = flag["details"]
    return {
        "flag_id": flag["id"],
        "type": flag["type"],
        "severity": flag["severity"],
        "field": d.get("field_label") or d.get("label"),
        "message": (d.get("message") or {}).get("en"),
        "values": [f"{c['value']} ({c['label']})" for c in d.get("candidates", [])],
        "status": flag["status"],
    }
