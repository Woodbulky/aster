import pytest
from pydantic import ValidationError

from app.research.packs import Pack, all_packs
from app.verify import requirements as rq

SRC = {"url": "https://mahadbt.maharashtra.gov.in/x", "quote": "Hostel Certificate (if required)"}


def pack(docs: list[dict], questions: list[dict] | None = None) -> Pack:
    return Pack.model_validate(
        {
            "scheme_key": "demo.req",
            "portal": "demo",
            "status": "draft",
            "name": {"en": "Req"},
            "department": "d",
            "official_urls": ["https://x.gov.in"],
            "summary": {"en": "s"},
            "criteria": [{"id": "c", "text": {"en": "c"}, "source": SRC}],
            "questions": questions or [],
            "documents": docs,
        }
    )


def doc(doc_type: str, **kw: object) -> dict:
    label = str(kw.get("id", doc_type))
    return {"doc_type": doc_type, "required": True, "text": {"en": label}, "source": SRC, **kw}


HOSTEL = pack(
    [
        doc("income_certificate"),
        doc(
            "other",
            id="hostel_certificate",
            required_if={"==": [{"var": "answers.hosteller"}, "yes"]},
        ),
        doc("other", id="declaration"),
        doc("admission_letter", id="admission", also_accepts=["fee_receipt"]),
        doc("other", id="cheque", stage="later"),
        doc("gap_certificate", required=False),
    ],
    [{"id": "hosteller", "text": {"en": "Do you live in a hostel?"}}],
)


def by_id(rows: list[dict]) -> dict[str, dict]:
    return {r["id"]: r for r in rows}


def d(i: str, t: str, status: str = "extracted", req: str | None = None) -> dict:
    return {"id": i, "doc_type": t, "status": status, "requirement_id": req}


def test_unknown_condition_is_a_question_not_optional() -> None:
    rows = by_id(rq.status(rq.from_pack(HOSTEL, "en"), {}, {}, []))
    h = rows["hostel_certificate"]
    assert h["need"] == "ask" and h["status"] == "missing"
    assert h["ask"]["id"] == "hosteller" and h["ask"]["options"] == ["yes", "no"]
    assert h in rq.blocking(list(rows.values()))


@pytest.mark.parametrize(
    "answer,need", [("yes", "required"), ("Yes", "required"), ("no", "not_needed")]
)
def test_answer_decides(answer: str, need: str) -> None:
    rows = by_id(rq.status(rq.from_pack(HOSTEL, "en"), {}, {"hosteller": answer}, []))
    assert rows["hostel_certificate"]["need"] == need


def test_other_documents_are_tracked_separately() -> None:
    docs = [d("1", "other", req="declaration")]
    rows = by_id(rq.status(rq.from_pack(HOSTEL, "en"), {}, {"hosteller": "yes"}, docs))
    assert rows["declaration"]["status"] == "extracted"
    assert rows["declaration"]["document_id"] == "1"
    assert rows["hostel_certificate"]["status"] == "missing"  # an "other" doesn't fill every slot
    blocking = {r["id"] for r in rq.blocking(list(rows.values()))}
    assert blocking == {"income_certificate", "hostel_certificate", "admission"}


def test_alternatives_and_stage() -> None:
    docs = [d("1", "fee_receipt"), d("2", "income_certificate", "failed")]
    rows = by_id(rq.status(rq.from_pack(HOSTEL, "en"), {}, {"hosteller": "no"}, docs))
    assert rows["admission"]["status"] == "extracted"  # a fee receipt is accepted
    assert rows["income_certificate"]["status"] == "failed"
    assert rows["cheque"]["need"] == "later"
    assert rows["gap_certificate"]["need"] == "optional"
    assert {r["id"] for r in rq.blocking(list(rows.values()))} == {
        "income_certificate",
        "declaration",
    }


def test_latest_upload_wins() -> None:
    docs = [d("1", "income_certificate"), d("2", "income_certificate", "processing")]
    rows = by_id(rq.status(rq.from_pack(HOSTEL, "en"), {}, {}, docs))
    assert rows["income_certificate"]["document_id"] == "2"


def test_profile_condition_names_the_missing_field() -> None:
    p = pack([doc("caste_validity", required_if={"==": [{"var": "profile.category"}, "SC"]})])
    [row] = rq.status(rq.from_pack(p, "en"), {}, {}, [])
    assert row["need"] == "ask" and row["ask"] == {"profile_field": "category"}
    [row] = rq.status(rq.from_pack(p, "en"), {"category": "OBC"}, {}, [])
    assert row["need"] == "not_needed"


def test_pack_validation() -> None:
    with pytest.raises(ValidationError, match="duplicate document ids"):
        pack([doc("other"), doc("other")])
    with pytest.raises(ValidationError, match="declare a question"):
        pack([doc("other", required_if={"==": [{"var": "answers.nope"}, "yes"]})])


def test_live_items() -> None:
    base = {
        "source_url": "https://a.org/p",
        "quote": "q" * 20,
        "site": "a.org",
        "fetched_on": "2026-10-05",
    }
    items = [
        {**base, "text": "Income certificate of parents"},  # saved before required existed
        {**base, "text": "Hostel receipt", "required": "if", "condition": "you live in a hostel"},
        {**base, "text": "Photo", "required": "optional", "doc_types": ["other"]},
    ]
    reqs = rq.from_live(items)
    assert reqs[0].doc_types == ["income_certificate"] and reqs[0].origin == "live"
    rows = by_id(rq.status(reqs, {}, {}, []))
    assert rows["live_0"]["need"] == "required"
    assert rows["live_1"]["need"] == "ask"
    assert "Only if: you live in a hostel" in rows["live_1"]["ask"]["text"]
    assert rows["live_2"]["need"] == "optional"
    rows = by_id(rq.status(reqs, {}, {"live_1": "no"}, []))
    assert rows["live_1"]["need"] == "not_needed"


def test_answers_from_field_values() -> None:
    eff = {
        "answers.hosteller": [{"value": "no", "status": "confirmed", "source_type": "voice"}],
        "full_name": [{"value": "A", "status": "candidate", "source_type": "document"}],
    }
    assert rq.answers(eff) == {"hosteller": "no"}


def test_doc_type_guess() -> None:
    assert rq.doc_type("12th marksheet") == "hsc_marksheet"
    assert rq.doc_type("Ration card") == "other"


def test_real_packs_build(monkeypatch: pytest.MonkeyPatch) -> None:
    from pathlib import Path

    from app.research import packs

    monkeypatch.setattr(packs, "KNOWLEDGE", Path(packs.__file__).resolve().parents[3] / "knowledge")
    all_packs.cache_clear()
    found = all_packs()
    assert len(found) == 8
    sc = found["mahadbt.goi_post_matric_sc"]
    rows = by_id(rq.status(rq.from_pack(sc, "mr"), {}, {}, []))
    assert rows["hostel_certificate"]["need"] == "ask"
    assert rows["hostel_certificate"]["ask"]["text"] == "तुम्ही वसतिगृहात राहता का?"
    all_packs.cache_clear()
