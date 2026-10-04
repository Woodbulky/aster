"""Documents Aster doesn't blindly trust: a file that might not be what its slot says (an EWS
certificate in the income slot), an income that is really a limit, and signals that a file was
edited or AI-generated. Never a verdict: block or warn, the student answers with a reason."""

import asyncio
from types import SimpleNamespace

import pymupdf
import pytest

from app.config import Settings
from app.verify import doctype, integrity, pipeline
from app.verify.checks import ResolveError, flag_card, resolve
from app.verify.extraction import Item
from tests.test_checks import Mem

EWS = [
    "GOVERNMENT OF MAHARASHTRA",
    "INCOME & ASSET CERTIFICATE TO BE PRODUCED BY ECONOMICALLY WEAKER SECTIONS",
    "Gross annual family income below Rs. 8,00,000/-",
]
INCOME = ["उत्पन्नाचा दाखला", "Income Certificate No. 2526/2025", "वार्षिक उत्पन्न रु. 1,48,000/-"]


def lines(texts: list[str]) -> list[dict]:
    return [
        {"id": f"L{i}", "page": 0, "text": t, "confidence": 1.0, "bbox": None}
        for i, t in enumerate(texts)
    ]


# ---------- which slot ----------
def test_an_ews_certificate_in_the_income_slot_is_questioned() -> None:
    m = doctype.check("income_certificate", lines(EWS))
    assert m and m.seen == "ews_certificate" and m.line_id == "L1"
    assert m.phrase.lower() == "economically weaker section"  # the words, not the line
    msg = doctype.message("income_certificate", m)
    assert msg["en"].startswith("This might not be your income certificate")
    assert "हा कदाचित" in msg["mr"] and "शायद" in msg["hi"]


@pytest.mark.parametrize(
    "slot,texts",
    [
        ("income_certificate", INCOME),  # it is one
        ("income_certificate", ["blurry", "unreadable scan 1,48,000"]),  # no title: never flagged
        ("income_certificate", ["INCOME CERTIFICATE", "valid for EWS reservation"]),  # mentions EWS
        ("aadhaar", EWS),  # slots without look-alikes are not checked
        (
            "ssc_marksheet",
            [
                "SECONDARY SCHOOL CERTIFICATE EXAMINATION",
                "Board of Secondary and Higher Secondary Education",
            ],
        ),
        (
            "hsc_marksheet",
            [
                "HIGHER SECONDARY CERTIFICATE EXAMINATION",
                "Board of Secondary and Higher Secondary Education",
            ],
        ),
    ],
)
def test_matching_or_unsure_documents_pass(slot: str, texts: list[str]) -> None:
    assert doctype.check(slot, lines(texts)) is None


def test_look_alikes_in_marathi_and_marksheets() -> None:
    assert (
        doctype.check("income_certificate", lines(["आर्थिकदृष्ट्या दुर्बल घटक प्रमाणपत्र"])).seen
        == "ews_certificate"
    )
    assert (
        doctype.check("income_certificate", lines(["Non-Creamy Layer Certificate"])).seen
        == "non_creamy_layer"
    )
    assert (
        doctype.check("ssc_marksheet", lines(["HIGHER SECONDARY CERTIFICATE EXAMINATION"])).seen
        == "hsc_marksheet"
    )


def test_income_limits() -> None:
    assert doctype.income_limit("Gross annual family income below Rs. 8,00,000/-") == "below"
    assert doctype.income_limit("उत्पन्न रु. 8,00,000 पेक्षा कमी") == "पेक्षा कमी"
    assert doctype.income_limit("वार्षिक उत्पन्न रु. 1,48,000/-") is None


# ---------- the file itself ----------
def _pdf(meta: dict | None = None) -> bytes:
    doc = pymupdf.open()
    doc.new_page().insert_text((50, 50), "Income Certificate")
    if meta:
        doc.set_metadata(meta)
    return doc.tobytes()


def test_file_signals() -> None:
    assert integrity.signals(_pdf(), "application/pdf") == []  # a plain PDF says nothing
    png = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 4, 4), False).tobytes("png")
    assert integrity.signals(png, "image/png") == []  # nor does a camera/scanner image
    canva = integrity.signals(_pdf({"producer": "Canva", "creator": "Canva"}), "application/pdf")
    assert canva == [integrity.Signal("edited_with", "warn", "Canva")]
    later = {"creationDate": "D:20250101000000", "modDate": "D:20250301000000"}
    assert integrity.signals(_pdf(later), "application/pdf") == [
        integrity.Signal("modified_later", "warn", "59")
    ]
    sd = (
        png[:33]
        + b"\x00\x00\x00\x40tEXtparameters\x00a certificate\nSteps: 20, Sampler: Euler a"
        + png[33:]
    )
    assert integrity.signals(sd, "image/png") == [
        integrity.Signal("ai_marker", "block", "Stable Diffusion")
    ]
    xmp = b"\xff\xd8\xff\xe1<x:xmpmeta>Iptc4xmpExt:DigitalSourceType=http://cv.iptc.org/newscodes/digitalsourcetype/trainedAlgorithmicMedia</x:xmpmeta>"
    assert integrity.signals(xmp, "image/jpeg")[0].code == "ai_marker"
    photoshop = b"\xff\xd8\xff\xe1Exif\x00\x00Software\x00Adobe Photoshop 25.0"
    assert integrity.signals(photoshop, "image/jpeg") == [
        integrity.Signal("edited_with", "warn", "Adobe Photoshop")
    ]


def test_the_wording_never_judges() -> None:
    msg = integrity.message([integrity.Signal("ai_marker", "block", "Midjourney")])
    assert "Midjourney" in msg["en"] and "can't tell whether a document is genuine" in msg["en"]
    for text in msg.values():
        assert not any(w in text.lower() for w in ("fake", "forged", "fraud", "नकली", "बनावट"))


# ---------- the pipeline ----------
class Run:
    """One document through pipeline._run with storage, OCR and extraction faked."""

    def __init__(self, mp: pytest.MonkeyPatch, mem: Mem) -> None:
        self.mem, self.extracted, self.removed = mem, 0, []
        mem.install(mp)
        mp.setattr(pipeline.repo, "get_session", lambda db, u, s: {"id": s, "scheme_key": None})
        mp.setattr(pipeline.repo, "update_document", lambda db, u, d, v: self.doc.update(v))
        self.items: list[Item] = []

        async def extract(s, doc_type, ls, u, sid):
            self.extracted += 1
            return self.items

        mp.setattr(pipeline, "extract", extract)

    def __call__(
        self,
        mp: pytest.MonkeyPatch,
        texts: list[str],
        file: bytes,
        doc_type: str = "income_certificate",
    ) -> dict:
        n = len(self.mem.docs) + 1
        self.doc = {
            "id": f"doc{n}",
            "session_id": "s1",
            "doc_type": doc_type,
            "mime": "application/pdf",
            "storage_path": f"u/s1/doc{n}.pdf",
            "status": "extracted",
            "ocr": {"pages": []},
        }
        self.mem.docs.append(self.doc)
        bucket = SimpleNamespace(
            download=lambda path: file,
            upload=lambda *a: None,
            remove=lambda p: self.removed.append(p),
        )
        db = SimpleNamespace(storage=SimpleNamespace(from_=lambda b: bucket))
        read = lines(texts)

        async def read_lines(s, pages, dt, u, sid):
            return read, "pdf_text"

        mp.setattr(pipeline, "read_lines", read_lines)
        asyncio.run(pipeline._run(Settings(_env_file=None), db, "u1", "s1", self.doc))
        return self.doc

    def read(self) -> list[str]:
        """Values read from documents (the checks also add the profile's values)."""
        return [f["value"] for f in self.mem.fields if f["source_type"] == "document"]

    def flags(self, code: str) -> list[dict]:
        return [f for f in self.mem.flags if f["reason_code"] == code]


def test_ews_in_the_income_slot_blocks_and_saves_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    run = Run(monkeypatch, Mem())
    run.items = [Item(field_key="annual_family_income", line_ids=["L2"], value_text="8,00,000")]
    doc = run(monkeypatch, EWS, _pdf())
    [flag] = run.flags("doc_type_mismatch")
    assert flag["severity"] == "block" and flag["details"]["document_id"] == doc["id"]
    assert run.extracted == 0 and run.read() == []  # nothing read from it
    assert (
        doc["ocr"]["missing"] == []
        and "might not be your income certificate" in doc["ocr"]["checks"][0]["text"]
    )
    kind, card = flag_card(flag, "mr")
    assert (card["can_pick"], card["can_type"]) == (False, False)  # answered with a reason only
    assert card["message"].startswith("हा कदाचित")
    with pytest.raises(ResolveError, match="only be answered with a reason"):
        resolve(None, "u1", "s1", flag["id"], reason="it is the income one", via="tap", value="x")

    # "it is the right document" -> read again, trusting its slot (the limit check is trusted too)
    from app.verify.checks import reread_after

    out = resolve(None, "u1", "s1", flag["id"], reason="the office gave me this one", via="tap")
    assert reread_after(out) == doc["id"]
    run.mem.docs.clear()
    run.doc = doc
    run.mem.docs.append(doc)

    async def again(s, pages, dt, u, sid):
        return lines(EWS), "pdf_text"

    monkeypatch.setattr(pipeline, "read_lines", again)
    bucket = SimpleNamespace(
        download=lambda p: _pdf(), upload=lambda *a: None, remove=lambda p: None
    )
    asyncio.run(
        pipeline._run(
            Settings(_env_file=None),
            SimpleNamespace(storage=SimpleNamespace(from_=lambda b: bucket)),
            "u1",
            "s1",
            doc,
        )
    )
    assert run.extracted == 1
    assert run.read() == ["800000"]
    assert len(run.flags("doc_type_mismatch")) == 1 and run.flags("income_is_a_limit") == []


def test_an_income_that_reads_like_a_limit_is_not_used(monkeypatch: pytest.MonkeyPatch) -> None:
    run = Run(monkeypatch, Mem())
    texts = ["INCOME CERTIFICATE", "Annual income below Rs. 8,00,000/-", "Certificate No. 12/2025"]
    run.items = [Item(field_key="annual_family_income", line_ids=["L1"], value_text="8,00,000")]
    doc = run(monkeypatch, texts, _pdf())
    [flag] = run.flags("income_is_a_limit")
    assert flag["severity"] == "block" and "“below”" in flag["details"]["message"]["en"]
    assert run.read() == [] and doc["ocr"]["failed"] == [
        {"field_key": "annual_family_income", "reason": "reads like a limit"}
    ]


def test_a_real_income_certificate_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    run = Run(monkeypatch, Mem())
    run.items = [Item(field_key="annual_family_income", line_ids=["L2"], value_text="1,48,000")]
    doc = run(monkeypatch, INCOME, _pdf())
    assert run.read() == ["148000"]
    assert [
        f["reason_code"]
        for f in run.mem.flags
        if f["reason_code"] in ("doc_type_mismatch", "income_is_a_limit", "integrity_signal")
    ] == []
    assert doc["ocr"]["checks"] == []


def test_an_edited_file_warns_but_is_still_read(monkeypatch: pytest.MonkeyPatch) -> None:
    run = Run(monkeypatch, Mem())
    run.items = [Item(field_key="annual_family_income", line_ids=["L2"], value_text="1,48,000")]
    doc = run(monkeypatch, INCOME, _pdf({"producer": "Canva"}))
    [flag] = run.flags("integrity_signal")
    assert flag["severity"] == "warn" and flag["details"]["signals"] == [
        {"code": "edited_with", "detail": "Canva"}
    ]
    assert "saved with Canva" in flag["details"]["message"]["en"]
    assert run.read() == ["148000"]  # a warning, not a block on reading
    assert (
        "document.integrity",
        {"document_id": doc["id"], "signals": ["edited_with"]},
    ) in run.mem.audit
    assert doc["ocr"]["checks"] == [{"severity": "warn", "text": "This file was saved with Canva."}]


def test_a_new_upload_closes_the_checks_on_the_file_it_replaced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = Run(monkeypatch, Mem())
    run(monkeypatch, EWS, _pdf())
    [old] = run.flags("doc_type_mismatch")
    run.items = [Item(field_key="annual_family_income", line_ids=["L2"], value_text="1,48,000")]
    run(monkeypatch, INCOME, _pdf())
    assert old["status"] == "resolved" and old["resolution"]["reason"] == "document replaced"
    assert run.read() == ["148000"]


def test_a_second_wrong_upload_is_asked_about_again(monkeypatch: pytest.MonkeyPatch) -> None:
    run = Run(monkeypatch, Mem())
    run(monkeypatch, EWS, _pdf())
    [first] = run.flags("doc_type_mismatch")
    resolve(None, "u1", "s1", first["id"], reason="I will upload another", via="tap")
    second = run(monkeypatch, EWS, _pdf())
    assert [
        f["details"]["document_id"] for f in run.flags("doc_type_mismatch") if f["status"] == "open"
    ] == [second["id"]]
