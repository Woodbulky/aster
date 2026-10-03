"""Cross-source checks on field_values candidates (VERIFICATION.md "Contradictions"). Pure: rows
in, findings out; checks.py reads and writes the database.

Names are not compared here: the name rules (rules/core.json) score them with names.py, so one
spelling problem is flagged once."""

import re
from dataclasses import dataclass
from itertools import combinations
from typing import Any

from rapidfuzz import fuzz

from app.verify import names
from app.verify.validator import ENUMS, KIND, norm, numbers, parse_date

Row = dict[str, Any]
# token_set_ratio: "Maharashtra State Board" == "Maharashtra State Board, Pune"
TEXT_SAME = 90
PERCENT_ROUNDING = 0.05 + 1e-9
_DEVANAGARI = re.compile(r"[ऀ-ॿ]")
# A disagreement on these blocks readiness; on free text (board, institute) it is a warning.
BLOCKING_KINDS = {"date", "amount", "percent", "year", "enum", "ifsc", "last4", "fy"}


def canon(field_key: str, value: Any) -> str:
    """Comparable form of a value from any source: "1,48,000" == "148000.0", "12/05/2005" ==
    "2005-05-12", "पुरुष" == "Male"."""
    v = str(value or "").strip()
    kind = KIND.get(field_key, "text")
    if kind == "name":
        return names.normalized(v)
    if kind == "date":
        d = parse_date(v)
        return d.isoformat() if d else norm(v)
    if kind in ("amount", "percent", "year"):
        n = numbers(v)
        return f"{n[0]:g}" if len(n) == 1 else norm(v)
    if kind == "enum":
        return ENUMS.get(norm(v), norm(v))
    return norm(v)


def same(field_key: str, a: Any, b: Any) -> bool:
    ca, cb = canon(field_key, a), canon(field_key, b)
    if KIND.get(field_key, "text") == "text":
        if bool(_DEVANAGARI.search(ca)) != bool(_DEVANAGARI.search(cb)):
            return True  # a Marathi board name vs an English one: a translation, not comparable
        return ca == cb or fuzz.token_set_ratio(ca, cb) >= TEXT_SAME
    if KIND.get(field_key) == "percent":
        try:  # people round: 69.83 on the marksheet, 69.8 in the profile
            return abs(float(ca) - float(cb)) <= PERCENT_ROUNDING
        except ValueError:
            return ca == cb
    return ca == cb


def source_key(r: Row) -> str:
    ref = r.get("source_ref") or {}
    return f"{r['source_type']}:{ref.get('document_id') or ''}"


def effective(rows: list[Row], live_docs: set[str]) -> dict[str, list[Row]]:
    """Candidates that still count, per field. A replaced document's candidates drop out; after a
    confirmation only the confirmed value and candidates that arrived later count (the user
    already chose between the older ones). Only the latest profile value counts. Rejected rows
    never count. Nothing is deleted."""
    out: dict[str, list[Row]] = {}
    for r in sorted(rows, key=lambda r: r["created_at"]):
        if r["status"] == "rejected":
            continue
        doc = (r.get("source_ref") or {}).get("document_id")
        if r["source_type"] == "document" and doc not in live_docs:
            continue
        if r["status"] == "confirmed":
            out[r["field_key"]] = [r]
            continue
        rows_ = out.setdefault(r["field_key"], [])
        if r["source_type"] == "profile":  # an edited profile replaces its older value
            rows_[:] = [
                x for x in rows_ if x["source_type"] != "profile" or x["status"] == "confirmed"
            ]
        rows_.append(r)
    return out


@dataclass(frozen=True)
class Disagreement:
    field_key: str
    severity: str  # block | warn
    candidates: list[Row]


def disagreements(eff: dict[str, list[Row]]) -> list[Disagreement]:
    out = []
    for key, rows in eff.items():
        kind = KIND.get(key, "text")
        if kind == "name" or len({source_key(r) for r in rows}) < 2:
            continue
        if any(not same(key, a["value"], b["value"]) for a, b in combinations(rows, 2)):
            out.append(Disagreement(key, "block" if kind in BLOCKING_KINDS else "warn", rows))
    return out


def best(rows: list[Row]) -> Row | None:
    """The value rules use: confirmed, else a document (highest confidence), else the rest."""
    if not rows:
        return None
    rank = {"resolution": 0, "document": 1, "aadhaar_qr": 1, "profile": 2, "voice": 3, "text": 3}
    return min(
        rows,
        key=lambda r: (
            r["status"] != "confirmed",
            rank.get(r["source_type"], 9),
            -(r.get("confidence") or 0),
        ),
    )


def name_match_min(rows: list[Row]) -> float | None:
    """Lowest pairwise score between the distinct spellings of the student's name."""
    vals = list({names.normalized(r["value"]): r["value"] for r in rows}.values())
    if not vals:
        return None
    if len(vals) == 1:
        return 100.0
    return min(names.score(a, b) for a, b in combinations(vals, 2))
