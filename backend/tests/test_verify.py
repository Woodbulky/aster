"""Validator, OCR redaction and masking (VERIFICATION.md steps 4-6)."""

import asyncio

import pymupdf
import pytest

from app.db.supabase import redact_ids
from app.verify import ocr
from app.verify.validator import check, norm

LINES = [
    {"id": "L0", "text": "INCOME CERTIFICATE", "confidence": 0.99},
    {"id": "L1", "text": "Shri Aarav Sunil Patil, resident of Pune", "confidence": 0.95},
    {"id": "L2", "text": "annual family income of Rs. 1,48,000/-", "confidence": 0.9},
    {"id": "L3", "text": "Date of issue : 15 / 06 / 2026", "confidence": 0.8},
    {"id": "L4", "text": "IFSC: SPCB0001234", "confidence": 1.0},
    {"id": "L5", "text": "Account No: [number ending 4417]", "confidence": 1.0},
    {"id": "L6", "text": "FEBRUARY 23", "confidence": 0.7},
    {"id": "L7", "text": "टक्केवारी ८७.४०", "confidence": 0.6},
    {"id": "L8", "text": "financial year 2025-26", "confidence": 1.0},
]


def test_rejects_value_not_in_cited_lines() -> None:
    """The acceptance test: an invented value never becomes a candidate."""
    assert not check("full_name", "Rohan Deshmukh", ["L1"], LINES).ok
    assert not check("annual_family_income", "120000", ["L2"], LINES).ok
    assert not check("income_cert_issue_date", "2026-06-16", ["L3"], LINES).ok
    assert not check("aadhaar_last4", "1234", ["L5"], LINES).ok


def test_rejects_value_from_another_line() -> None:
    """Right value, wrong citation: the cited line must hold it."""
    assert not check("annual_family_income", "148000", ["L1"], LINES).ok


def test_rejects_unknown_line_ids() -> None:
    assert not check("full_name", "Aarav Sunil Patil", ["L99"], LINES).ok
    assert not check("full_name", "Aarav Sunil Patil", ["L1", "L99"], LINES).ok


def test_accepts_and_normalises() -> None:
    name = check("full_name", "Shri Aarav Sunil Patil", ["L1"], LINES)
    assert (name.ok, name.value, name.confidence) == (True, "Aarav Sunil Patil", 0.95)
    assert check("annual_family_income", "Rs. 1,48,000/-", ["L2"], LINES).value == "148000"
    assert check("annual_family_income", "148000", ["L2"], LINES).ok  # parsed, not substring
    assert check("income_cert_issue_date", "15/06/2026", ["L3"], LINES).value == "2026-06-15"
    assert check("bank_ifsc", "spcb0001234", ["L4"], LINES).value == "SPCB0001234"
    assert check("bank_account_last4", "4417", ["L5"], LINES).ok
    assert check("hsc_year", "23", ["L6"], LINES).value == "2023"  # 2-digit exam year
    assert check("hsc_year", "2023", ["L6"], LINES).ok
    pct = check("ssc_percentage", "87.40", ["L7"], LINES)  # Devanagari digits
    assert (pct.ok, pct.value, pct.confidence) == (True, "87.4", 0.6)
    assert check("income_cert_fy", "2025-26", ["L8"], LINES).ok


def test_type_checks() -> None:
    bad_ifsc = [{"id": "L0", "text": "IFSC: SPCB1001234", "confidence": 1}]
    assert not check("bank_ifsc", "SPCB1001234", ["L0"], bad_ifsc).ok  # 5th char must be 0
    totals = [{"id": "L0", "text": "TOTAL 432", "confidence": 1}]
    assert not check("ssc_percentage", "432", ["L0"], totals).ok  # total marks, not a %
    assert not check("hsc_year", "1832", ["L0"], [{"id": "L0", "text": "1832", "confidence": 1}]).ok
    assert not check("aadhaar_last4", "44", ["L5"], LINES).ok


def test_fuzzy_text_halves_confidence() -> None:
    lines = [{"id": "L0", "text": "Board: Maharashtra State Bord, Pune", "confidence": 1.0}]
    c = check("ssc_board", "Maharashtra State Board", ["L0"], lines)
    assert (c.ok, c.confidence) == (True, 0.5)


def test_norm() -> None:
    assert norm("  Rs. १,४८,०००/-  ") == "rs. 1 48 000/-"


def test_split_aadhaar_groups_are_merged_then_redacted() -> None:
    raw = [
        ("Name", 1.0, [0, 0, 5, 5]),
        ("1234", 0.9, [10, 10, 50, 20]),
        ("5678", 0.8, [55, 10, 95, 20]),
        ("9012", 0.9, [100, 10, 140, 20]),
        ("DOB", 1.0, [0, 30, 10, 40]),
    ]
    merged = ocr.merge_digit_groups(raw)
    assert merged[1] == ("1234 5678 9012", 0.8, [10, 10, 140, 20])
    assert redact_ids(merged[1][0]) == "[number ending 9012]"


def _pdf(lines: list[str]) -> bytes:
    doc = pymupdf.open()
    page = doc.new_page(width=400, height=200)
    for i, t in enumerate(lines):
        page.insert_text((20, 40 + 30 * i), t, fontsize=12)
    return doc.tobytes()


def test_text_layer_lines_are_redacted_and_page_masked() -> None:
    from app.config import Settings

    data = _pdf(["Name: Aarav Sunil Patil", "Number: 0000 1111 4417 and more text here"])
    pages = ocr.render(data, "application/pdf")
    before = pages[0].png
    lines, engine = asyncio.run(
        ocr.read_lines(Settings(_env_file=None), pages, "aadhaar", "u", "s")
    )
    assert engine == "pdf_text"
    assert lines[1]["text"] == "Number: [number ending 4417] and more text here"
    assert all("0000 1111" not in ln["text"] for ln in lines)
    assert pages[0].png != before  # the number was drawn over


def test_no_engine_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import Settings

    monkeypatch.setattr(ocr, "_gpu_ocr", lambda s, png: None)
    blank = pymupdf.open()
    blank.new_page(width=100, height=100)
    pages = ocr.render(blank.tobytes(), "application/pdf")
    with pytest.raises(ocr.OcrUnavailable):  # Aadhaar scans never go to the vision fallback
        asyncio.run(ocr.read_lines(Settings(_env_file=None), pages, "aadhaar", "u", "s"))


def test_vision_fallback_lines_have_no_bbox(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import Settings

    async def fake_vision(s, png, user_id, session_id):
        return ["INCOME CERTIFICATE", "Income Rs. 1,48,000/-"]

    monkeypatch.setattr(ocr, "_gpu_ocr", lambda s, png: None)
    monkeypatch.setattr(ocr, "_vision_lines", fake_vision)
    blank = pymupdf.open()
    blank.new_page(width=100, height=100)
    pages = ocr.render(blank.tobytes(), "application/pdf")
    lines, engine = asyncio.run(
        ocr.read_lines(Settings(_env_file=None), pages, "income_certificate", "u", "s")
    )
    assert engine == "vision_llm"
    assert [(ln["bbox"], ln["confidence"]) for ln in lines] == [(None, 0.7), (None, 0.7)]
