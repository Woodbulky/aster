"""Deterministic check of every extracted value against the OCR lines it cites (VERIFICATION.md
step 6). The LLM points at lines; this decides whether the value is really there. No pass, no
candidate (guardrail 2)."""

import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Literal

from rapidfuzz import fuzz

Kind = Literal["text", "name", "date", "amount", "percent", "year", "ifsc", "last4", "fy", "enum"]
KIND: dict[str, Kind] = {
    "full_name": "name",
    "father_name": "name",
    "mother_name": "name",
    "account_holder_name": "name",
    "dob": "date",
    "income_cert_issue_date": "date",
    "annual_family_income": "amount",
    "ssc_percentage": "percent",
    "hsc_percentage": "percent",
    "ssc_year": "year",
    "hsc_year": "year",
    "current_year": "year",
    "bank_ifsc": "ifsc",
    "aadhaar_last4": "last4",
    "bank_account_last4": "last4",
    "income_cert_fy": "fy",
    "gender": "enum",
    "category": "enum",
}
FUZZY = 0.5  # type-check factor for a text value found only approximately (OCR noise)
FUZZY_MIN = 90
_DEV_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")
_IFSC = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")
_HONORIFIC = re.compile(r"^(?:shri|shree|smt|kumari|kum|ku|mr|mrs|ms|miss)\.?\s+", re.IGNORECASE)
_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")
_DATE_FORMATS = ("%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%Y-%m-%d", "%d %B %Y", "%d %b %Y")
_DATE_IN_TEXT = re.compile(
    r"\d{1,2}[/.-]\d{1,2}[/.-]\d{4}|\d{4}-\d{2}-\d{2}|\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}"
)


def norm(s: str) -> str:
    """NFKC, Devanagari digits -> ASCII, casefold, punctuation (except / - .) -> space, collapse."""
    s = unicodedata.normalize("NFKC", s).translate(_DEV_DIGITS).casefold()
    s = re.sub(r"[^\w\s/.-]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def parse_date(s: str) -> date | None:
    s = re.sub(r"\s+", " ", s.strip())
    for f in _DATE_FORMATS:  # day-first: Indian documents write 12/05/2005
        try:
            return datetime.strptime(s, f).date()
        except ValueError:
            continue
    return None


def numbers(s: str) -> list[float]:
    """Indian grouping kept: "Rs. 1,48,000/-" -> [148000.0]."""
    digits = unicodedata.normalize("NFKC", s).translate(_DEV_DIGITS)
    return [float(m.replace(",", "")) for m in _NUM.findall(digits)]


@dataclass(frozen=True)
class Checked:
    ok: bool
    value: str = ""  # normalised display value: ISO date, plain number, ...
    confidence: float = 0.0
    reason: str = ""


def check(
    field_key: str, value_text: str, line_ids: list[str], lines: list[dict[str, Any]]
) -> Checked:
    """lines: the document's OCR lines [{id, text, confidence}]."""
    by_id = {ln["id"]: ln for ln in lines}
    cited = [by_id[i] for i in line_ids if i in by_id]
    if not cited or len(cited) != len(line_ids):
        return Checked(False, reason="cites lines that do not exist")
    value_text = value_text.strip()
    if not value_text:
        return Checked(False, reason="empty value")
    text = " ".join(ln["text"] for ln in cited)
    conf = min(float(ln.get("confidence") or 0) for ln in cited)
    kind = KIND.get(field_key, "text")
    factor = 1.0

    if kind == "date":
        d = parse_date(value_text)
        # OCR often spaces the separators: "12 / 05 / 2005"
        squeezed = re.sub(r"\s*([/.-])\s*", r"\1", text)
        found = {parse_date(m) for m in _DATE_IN_TEXT.findall(squeezed)}
        if not d or d not in found:
            return Checked(False, reason="date not found in the cited lines")
        value = d.isoformat()
    elif kind in ("amount", "percent", "year"):
        nums = numbers(value_text)
        if len(nums) != 1:
            return Checked(False, reason="not a single number")
        n = nums[0]
        tol = 0.01 if kind == "percent" else 0.0
        found = numbers(text)
        exam_year = kind == "year" and field_key != "current_year"
        if exam_year:  # "FEBRUARY 23" on Maharashtra HSC marksheets: 2-digit years are 20xx
            n = n + 2000 if n < 100 else n
            found = [x + 2000 if x < 100 else x for x in found]
        if not any(abs(n - x) <= tol for x in found):
            return Checked(False, reason="number not found in the cited lines")
        if exam_year:
            if not 1950 <= n <= date.today().year + 1:
                return Checked(False, reason="implausible year")
        if field_key == "current_year" and not 1 <= n <= 6:
            return Checked(False, reason="implausible year of study")
        if kind == "percent" and not 0 < n <= 100:
            return Checked(False, reason="implausible percentage")
        value = f"{n:g}" if kind != "amount" else str(int(n)) if n == int(n) else str(n)
    elif kind == "last4":
        if not re.fullmatch(r"\d{4}", value_text) or value_text not in text:
            return Checked(False, reason="last 4 digits not found in the cited lines")
        value = value_text
    elif kind == "ifsc":
        value = value_text.upper().replace(" ", "")
        if not _IFSC.match(value) or value.casefold() not in norm(text).replace(" ", ""):
            return Checked(False, reason="IFSC invalid or not in the cited lines")
    else:
        nv, nt = norm(value_text), norm(text)
        if nv not in nt:
            if fuzz.partial_ratio(nv, nt) < FUZZY_MIN:
                return Checked(False, reason="value not found in the cited lines")
            factor = FUZZY
        if kind == "fy" and not re.fullmatch(r"\d{4}\s*-\s*\d{2,4}", value_text):
            return Checked(False, reason="not a financial year")
        value = re.sub(r"\s+", " ", value_text)
        if kind == "name":
            value = _HONORIFIC.sub("", value)
    return Checked(True, value=value, confidence=round(conf * factor, 3))
