"""Contradictions, rules, flags and resolution (VERIFICATION.md), on an in-memory repo."""

import itertools
from datetime import date, timedelta

import pytest

from app.agent.phases import next_phase
from app.db import supabase as repo
from app.verify import checks
from app.verify.contradictions import canon, effective, same

UID, SID = "u1", "s1"
SESSION = {"id": SID, "scheme_key": "demo.obc_aid", "phase": "documents"}
_ids = itertools.count(1)
_clock = itertools.count(1)


class Mem:
    def __init__(self) -> None:
        self.profile: dict = {
            "full_name": "Aarav Sunil Patil",
            "annual_family_income": 120000.0,
            "dob": "2005-05-12",
            "gender": "Male",
            "ssc_year": 2021,
        }
        self.fields: list[dict] = []
        self.docs: list[dict] = []
        self.flags: list[dict] = []
        self.evals: list[dict] = []
        self.audit: list[tuple[str, dict]] = []

    def stamp(self) -> str:
        return f"2026-10-03T10:{next(_clock):05d}"

    def install(self, mp: pytest.MonkeyPatch) -> None:
        mp.setattr(repo, "get_profile", lambda db, u: dict(self.profile))
        mp.setattr(repo, "list_profile_sources", lambda db, u: [])
        mp.setattr(repo, "list_field_values", lambda db, u, s: list(self.fields))
        mp.setattr(repo, "list_documents", lambda db, u, s, full=False: list(self.docs))
        mp.setattr(
            repo,
            "list_flags",
            lambda db, u, s, status=None: [f for f in self.flags if status in (None, f["status"])],
        )
        mp.setattr(
            repo, "get_flag", lambda db, u, i: next((f for f in self.flags if f["id"] == i), None)
        )
        mp.setattr(repo, "add_rule_evaluations", lambda db, u, s, rows: self.evals.extend(rows))
        mp.setattr(
            repo, "write_audit", lambda db, u, s, a, p, actor="system": self.audit.append((a, p))
        )

        real_add = (
            repo.add_field_value.__wrapped__
            if hasattr(repo.add_field_value, "__wrapped__")
            else None
        )
        assert real_add is None

        def add_field_value(db, u, s, values):
            if not values.get("source_type") or not values.get("source_ref"):
                raise ValueError("a field value needs source_type and source_ref")
            row = {"id": f"fv{next(_ids)}", "created_at": self.stamp(), **values}
            self.fields.append(row)
            return row

        def add_flag(db, u, s, values):
            row = {"id": f"fl{next(_ids)}", "session_id": s, "status": "open", **values}
            self.flags.append(row)
            return row

        def update_flag(db, u, i, values):
            next(f for f in self.flags if f["id"] == i).update(values)

        mp.setattr(repo, "add_field_value", add_field_value)
        mp.setattr(repo, "add_flag", add_flag)
        mp.setattr(repo, "update_flag", update_flag)

    def doc(self, doc_type: str, **fields: str) -> str:
        d = {
            "id": f"d{next(_ids)}",
            "doc_type": doc_type,
            "status": "extracted",
            "ocr": {"pages": []},
        }
        self.docs.append(d)
        for k, v in fields.items():
            self.fields.append(
                {
                    "id": f"fv{next(_ids)}",
                    "created_at": self.stamp(),
                    "field_key": k,
                    "value": v,
                    "source_type": "document",
                    "source_ref": {
                        "document_id": d["id"],
                        "doc_type": doc_type,
                        "line_ids": ["L1"],
                        "page": 0,
                        "bbox": [],
                    },
                    "confidence": 1.0,
                    "status": "candidate",
                }
            )
        return d["id"]

    def open_flags(self) -> list[tuple[str, str, str]]:
        return sorted(
            (f["type"], f["reason_code"], f["field_key"])
            for f in self.flags
            if f["status"] == "open"
        )


@pytest.fixture
def mem(monkeypatch: pytest.MonkeyPatch) -> Mem:
    m = Mem()
    m.install(monkeypatch)
    return m


def demo_docs(m: Mem) -> None:
    m.doc(
        "aadhaar",
        full_name="Aarav Sunil Patil",
        dob="2005-05-12",
        gender="Male",
        aadhaar_last4="4417",
    )
    m.doc("ssc_marksheet", full_name="PATIL AARAV SUNIL", ssc_year="2021", ssc_percentage="87.4")
    m.doc(
        "income_certificate",
        full_name="Aarav Sunil Patil",
        annual_family_income="148000",
        income_cert_issue_date="2026-06-15",
    )
    m.doc(
        "bank_passbook",
        account_holder_name="AARV SUNIL PATIL",
        bank_ifsc="SPCB0001234",
        bank_account_last4="4417",
    )


def test_demo_documents_raise_exactly_the_seeded_problems(mem: Mem) -> None:
    demo_docs(mem)
    new = checks.run_checks(None, UID, SESSION, include_missing=False)
    assert mem.open_flags() == [
        ("contradiction", "value_mismatch", "annual_family_income"),
        ("rule", "bank_holder_spelling_variation", "account_holder_name"),
    ]
    income = next(f for f in new if f["field_key"] == "annual_family_income")
    assert income["severity"] == "block"
    assert sorted(c["value"] for c in income["details"]["candidates"]) == ["120000", "148000"]
    assert {c["label"] for c in income["details"]["candidates"]} == {
        "Your profile",
        "Income certificate · L1",
    }
    assert len(mem.evals) == 7  # every rule evaluated and logged
    assert {a for a, _ in mem.audit} == {"flag.raised"}


def test_document_being_finished_counts(mem: Mem) -> None:
    """Regression (live run): the pipeline checks before the status flips to extracted, so the
    passbook's own values were ignored and its name variation was never flagged."""
    demo_docs(mem)
    passbook = mem.docs[-1]
    passbook["status"] = "processing"
    checks.run_checks(None, UID, SESSION, include_missing=False)
    assert ("rule", "bank_holder_spelling_variation", "account_holder_name") not in mem.open_flags()
    checks.run_checks(None, UID, SESSION, include_missing=False, just_read=passbook["id"])
    assert ("rule", "bank_holder_spelling_variation", "account_holder_name") in mem.open_flags()


def test_rerun_does_not_duplicate(mem: Mem) -> None:
    demo_docs(mem)
    checks.run_checks(None, UID, SESSION, include_missing=False)
    n_fields = len(mem.fields)
    assert checks.run_checks(None, UID, SESSION, include_missing=False) == []
    assert len(mem.flags) == 2
    assert len(mem.fields) == n_fields  # profile candidates are added once


def test_pick_resolves_and_keeps_evidence(mem: Mem) -> None:
    demo_docs(mem)
    checks.run_checks(None, UID, SESSION, include_missing=False)
    flag = next(f for f in mem.flags if f["field_key"] == "annual_family_income")
    doc_cand = next(c for c in flag["details"]["candidates"] if c["source_type"] == "document")
    before = [dict(r) for r in mem.fields]
    out = checks.resolve(
        None,
        UID,
        SID,
        flag["id"],
        reason="the certificate is newer",
        via="tap",
        candidate_id=doc_cand["id"],
    )
    assert out["status"] == "resolved"
    confirmed = mem.fields[-1]
    assert (confirmed["status"], confirmed["value"], confirmed["source_type"]) == (
        "confirmed",
        "148000",
        "resolution",
    )
    assert confirmed["source_ref"]["candidate_id"] == doc_cand["id"]
    assert confirmed["resolution_reason"] == "the certificate is newer"
    assert mem.fields[: len(before)] == before  # candidates never edited (guardrail 3)
    assert checks.run_checks(None, UID, SESSION, include_missing=False) == []
    assert (
        "flag.resolved",
        {"flag_id": flag["id"], "field_key": "annual_family_income", "via": "tap"},
    ) in mem.audit


def test_typed_value_and_voice_evidence(mem: Mem) -> None:
    demo_docs(mem)
    checks.run_checks(None, UID, SESSION, include_missing=False)
    flag = next(f for f in mem.flags if f["field_key"] == "annual_family_income")
    checks.resolve(
        None,
        UID,
        SID,
        flag["id"],
        reason="new certificate",
        via="voice",
        value="150000",
        message_id="m9",
    )
    row = mem.fields[-1]
    assert (row["value"], row["source_ref"]["via"], row["source_ref"]["message_id"]) == (
        "150000",
        "voice",
        "m9",
    )


def test_acknowledged_warning_stays_quiet(mem: Mem) -> None:
    demo_docs(mem)
    checks.run_checks(None, UID, SESSION, include_missing=False)
    flag = next(f for f in mem.flags if f["type"] == "rule")
    checks.resolve(None, UID, SID, flag["id"], reason="bank short form, correcting it", via="tap")
    assert flag["status"] == "acknowledged"
    assert checks.run_checks(None, UID, SESSION, include_missing=False) == []


@pytest.mark.parametrize(
    ("kw", "msg"),
    [
        ({"reason": " "}, "reason"),
        ({"reason": "ok ok", "candidate_id": "nope"}, "not one of"),
        ({"reason": "ok ok", "candidate_id": "x", "value": "1"}, "not both"),
        ({"reason": "ok ok", "value": "  "}, "empty"),
    ],
)
def test_resolve_rejects_bad_answers(mem: Mem, kw: dict, msg: str) -> None:
    demo_docs(mem)
    checks.run_checks(None, UID, SESSION, include_missing=False)
    flag = next(f for f in mem.flags if f["field_key"] == "annual_family_income")
    with pytest.raises(checks.ResolveError, match=msg):
        checks.resolve(None, UID, SID, flag["id"], via="tap", **kw)
    assert flag["status"] == "open"


def test_resolve_twice_and_foreign_session(mem: Mem) -> None:
    demo_docs(mem)
    checks.run_checks(None, UID, SESSION, include_missing=False)
    flag = mem.flags[0]
    with pytest.raises(checks.ResolveError, match="no such flag"):
        checks.resolve(None, UID, "other", flag["id"], reason="fine fine", via="tap")
    checks.resolve(None, UID, SID, flag["id"], reason="fine fine", via="tap")
    with pytest.raises(checks.ResolveError, match="already"):
        checks.resolve(None, UID, SID, flag["id"], reason="fine fine", via="tap")


def test_replaced_document_no_longer_counts(mem: Mem) -> None:
    mem.doc("income_certificate", annual_family_income="148000")
    checks.run_checks(None, UID, SESSION, include_missing=False)
    assert mem.open_flags() == [("contradiction", "value_mismatch", "annual_family_income")]
    mem.flags.clear()
    mem.doc("income_certificate", annual_family_income="1,20,000")  # corrected upload
    assert checks.run_checks(None, UID, SESSION, include_missing=False) == []


def test_name_rules(mem: Mem) -> None:
    mem.profile["full_name"] = "Rohan Deshmukh"
    mem.doc("aadhaar", full_name="Aarav Sunil Patil")
    checks.run_checks(None, UID, SESSION, include_missing=False)
    flag = next(f for f in mem.flags if f["reason_code"] == "name_mismatch")
    assert flag["severity"] == "block"
    kind, card = checks.flag_card(flag, "mr")
    assert (kind, card["can_pick"], len(card["candidates"])) == ("contradiction", True, 2)
    assert "नाव" in card["message"]
    pick = next(c for c in card["candidates"] if c["source_type"] == "document")
    checks.resolve(
        None, UID, SID, flag["id"], reason="Aadhaar is correct", via="tap", candidate_id=pick["id"]
    )
    assert checks.run_checks(None, UID, SESSION, include_missing=False) == []


def test_hsc_year_and_old_certificate_rules(mem: Mem) -> None:
    old = (date.today() - timedelta(days=500)).isoformat()
    mem.doc("hsc_marksheet", hsc_year="2020")
    mem.doc("income_certificate", income_cert_issue_date=old, annual_family_income="120000")
    checks.run_checks(None, UID, SESSION, include_missing=False)
    assert ("rule", "hsc_before_ssc", "hsc_year") in mem.open_flags()
    assert ("rule", "income_cert_old", "income_cert_issue_date") in mem.open_flags()


def test_missing_required_document_then_uploaded(mem: Mem) -> None:
    checks.run_checks(None, UID, SESSION, include_missing=False)
    assert mem.flags == []  # not after every upload
    checks.run_checks(None, UID, SESSION, include_missing=True)
    assert mem.open_flags() == [("missing_doc", "required_doc_missing", "income_certificate")]
    kind, card = checks.flag_card(mem.flags[0], "en")
    assert (kind, card["can_pick"], card["can_type"]) == ("missing_item", False, False)
    with pytest.raises(checks.ResolveError, match="only be acknowledged"):
        checks.resolve(None, UID, SID, mem.flags[0]["id"], reason="ok ok", via="tap", value="x")
    mem.doc("income_certificate", annual_family_income="120000")
    checks.run_checks(None, UID, SESSION, include_missing=True)
    assert mem.flags[0]["status"] == "resolved"
    assert mem.flags[0]["resolution"]["by"] == "system"


def test_requirements_question_other_docs_and_answer(
    mem: Mem, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.test_requirements import HOSTEL

    monkeypatch.setattr(checks, "usable_packs", lambda: {"demo.hostel": HOSTEL})
    session = {"id": SID, "scheme_key": "demo.hostel", "phase": "verification"}
    mem.doc("income_certificate", annual_family_income="120000")
    mem.doc("other")
    mem.docs[-1]["requirement_id"] = "declaration"
    checks.run_checks(None, UID, session, include_missing=True)
    assert mem.open_flags() == [
        ("missing_doc", "required_doc_missing", "admission"),
        ("missing_doc", "requirement_question", "hostel_certificate"),
    ]
    q = next(f for f in mem.flags if f["reason_code"] == "requirement_question")
    kind, card = checks.flag_card(q, "en")
    assert kind == "missing_item" and card["doc"]["question"]["id"] == "hosteller"
    assert card["doc"]["doc_type"] == "other"  # the upload slot, not the requirement id

    with pytest.raises(checks.AnswerError, match="one of"):
        checks.record_answer(
            None, UID, session, "hosteller", "maybe", source_type="text", message_id="m1", via="tap"
        )
    checks.record_answer(
        None, UID, session, "hosteller", "Yes", source_type="voice", message_id="m1", via="voice"
    )
    answer = mem.fields[-1]
    assert (answer["field_key"], answer["value"], answer["status"]) == (
        "answers.hosteller",
        "yes",
        "confirmed",
    )
    assert answer["source_ref"]["message_id"] == "m1"  # guardrail 2
    assert q["status"] == "resolved" and q["resolution"]["reason"] == "answered"
    # "yes" makes the hostel certificate required: asked again as a missing document.
    assert ("missing_doc", "required_doc_missing", "hostel_certificate") in mem.open_flags()

    checks.record_answer(
        None, UID, session, "hosteller", "no", source_type="text", message_id="m2", via="tap"
    )
    assert ("missing_doc", "required_doc_missing", "hostel_certificate") not in mem.open_flags()
    mem.doc("fee_receipt", institute_name="X College")  # accepted for "admission"
    checks.run_checks(None, UID, session, include_missing=True)
    assert mem.open_flags() == []
    r = checks.readiness(None, UID, session)
    assert r["documents"] == ["income_certificate", "declaration", "admission"]
    assert not any(f["field_key"].startswith("answers.") for f in r["fields"])


def test_low_confidence_value_is_flagged(mem: Mem) -> None:
    mem.doc("aadhaar", gender="Male")
    mem.fields[-1]["confidence"] = 0.4
    checks.run_checks(None, UID, SESSION, include_missing=False)
    assert mem.open_flags() == [("low_confidence", "low_confidence", "gender")]


def test_edited_profile_replaces_older_profile_value(mem: Mem) -> None:
    mem.doc("income_certificate", annual_family_income="148000")
    checks.run_checks(None, UID, SESSION, include_missing=False)
    mem.flags.clear()
    mem.profile["annual_family_income"] = 148000
    assert checks.run_checks(None, UID, SESSION, include_missing=False) == []


def test_canon_and_same() -> None:
    assert canon("annual_family_income", "1,48,000") == canon("annual_family_income", 148000.0)
    assert canon("dob", "12/05/2005") == canon("dob", "2005-05-12")
    assert same("gender", "पुरुष", "Male")
    assert same("category", "इतर मागास वर्ग", "OBC")
    assert same("ssc_board", "Maharashtra State Board", "Maharashtra State Board, Pune Division")
    assert same("ssc_percentage", "87.40", 87.4)
    assert not same("annual_family_income", "148000", "120000")


def test_effective_keeps_confirmed_and_later() -> None:
    r = lambda i, t, st="candidate", src="voice": {  # noqa: E731
        "id": i,
        "created_at": t,
        "field_key": "dob",
        "value": i,
        "source_type": src,
        "status": st,
        "source_ref": {},
    }
    rows = [
        r("a", "1"),
        r("b", "2", "confirmed", "resolution"),
        r("c", "3"),
        r("d", "4", "rejected"),
    ]
    assert [x["id"] for x in effective(rows, set())["dob"]] == ["b", "c"]


def test_field_value_needs_a_source() -> None:
    with pytest.raises(ValueError, match="source"):
        repo.add_field_value(
            None, UID, SID, {"field_key": "dob", "value": "x", "source_type": "document"}
        )


def test_rule_files_load_and_use_known_facts() -> None:
    rules = [r for rs in checks.rulesets() for r in rs.rules]
    assert len(rules) == 7
    assert all(set(r.message) == {"en", "hi", "mr"} for r in rules)


@pytest.mark.parametrize(
    ("phase", "blocks", "expected"),
    [
        ("documents", 0, "documents"),  # documents -> verification is run_verification's call
        ("verification", 1, "verification"),
        ("verification", 0, "ready"),
        ("ready", 1, "verification"),  # a new blocking problem sends the user back
    ],
)
def test_verification_phases(phase: str, blocks: int, expected: str) -> None:
    assert next_phase({"phase": phase}, {}, True, blocks) == expected


def test_hard_to_read_values_stay_out_of_comparisons(mem: Mem) -> None:
    """Seen live: "9310" read as gender at low confidence raised a blocking gender mismatch."""
    mem.doc("aadhaar", gender="Male", full_name="Rohan Deshmukh")
    for r in mem.fields:
        r["confidence"] = 0.3
    checks.run_checks(None, UID, SESSION, include_missing=False)
    assert mem.open_flags() == [
        ("low_confidence", "low_confidence", "full_name"),
        ("low_confidence", "low_confidence", "gender"),
    ]


def test_rounded_percentage_and_cross_script_board_agree(mem: Mem) -> None:
    mem.profile |= {"hsc_percentage": 69.8, "hsc_board": "Maharashtra state board"}
    mem.doc(
        "hsc_marksheet",
        hsc_percentage="69.83",
        hsc_board="महाराष्ट्र राज्य माध्यमिक व उच्च माध्यमिक शिक्षण मंडळ, पुणे",
    )
    assert checks.run_checks(None, UID, SESSION, include_missing=False) == []


def test_typed_scheme_name_finds_its_pack(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.agent.tools import forms

    assert forms.pack_for_name("OBC aid") == "demo.obc_aid"
    assert forms.pack_for_name("Reliance Foundation scholarship") is None
    assert forms.pack_for_name("scholarship") is None  # ambiguous: no guess
    # Seen live: "hi" picked a pack as a piece of "Shikshan"; small talk names no scheme.
    for said in ("hi", "Hi Aster", "ok", "I am OBC", "I am open category"):
        assert forms.pack_for_name(said) is None, said
    assert forms.pack_for_name("OBC") == "demo.obc_aid"  # just the name
    assert forms.pack_for_name("I want the open merit aid") == "demo.open_merit"
    # Seen: the only usable pack was picked for "LIC scholarship" on the word "scholarship".
    only = {"demo.obc_aid": forms.usable_packs()["demo.obc_aid"]}
    monkeypatch.setattr(forms, "usable_packs", lambda: only)
    assert forms.pack_for_name("LIC scholarship") is None
    assert forms.pack_for_name("मला ओबीसी मदत शिष्यवृत्ती हवी") == "demo.obc_aid"
    assert forms.pack_for_name("मला खुली शिष्यवृत्ती हवी") is None  # no shared vowel-sign scraps


SAID = "1,48,000 is right, the certificate is latest. 12th year is 2025, I passed 12th in 2025"


def _ctx(message_id: str | None = "m7", input_mode: str = "voice", said: str = SAID):
    from app.agent.tools import Ctx

    return Ctx(None, UID, dict(SESSION, phase="verification"), "en", message_id, input_mode, said)


def test_resolve_by_voice_maps_words_to_a_candidate(mem: Mem) -> None:
    from app.agent.tools import run_tool

    demo_docs(mem)
    checks.run_checks(None, UID, SESSION, include_missing=False)
    flag = next(f for f in mem.flags if f["field_key"] == "annual_family_income")
    args = {"flag_id": flag["id"], "choice": "1,48,000", "reason": "the certificate is latest"}
    res = run_tool(_ctx(), "resolve_flag", args)
    assert res.ok and res.card.payload["status"] == "resolved"
    row = mem.fields[-1]
    assert (row["value"], row["status"]) == ("148000", "confirmed")
    assert (row["source_ref"]["via"], row["source_ref"]["message_id"]) == ("voice", "m7")
    assert row["source_ref"]["candidate_id"]  # points at the certificate's value


def test_resolve_flag_needs_the_users_own_words(mem: Mem) -> None:
    from app.agent.tools import run_tool

    demo_docs(mem)
    checks.run_checks(None, UID, SESSION, include_missing=False)
    flag = next(f for f in mem.flags if f["field_key"] == "annual_family_income")
    args = {"flag_id": flag["id"], "choice": "148000", "reason": "certificate"}
    assert "own words" in run_tool(_ctx(input_mode="ui"), "resolve_flag", args).error
    invented = args | {"reason": "the income certificate was issued by the Tehsildar"}
    assert "user's own words" in run_tool(_ctx(), "resolve_flag", invented).error
    bad = run_tool(_ctx(), "resolve_flag", args | {"choice": "99000"})
    assert "one of ['120000', '148000']" in bad.error
    assert flag["status"] == "open"


def test_typed_year_fixes_the_hsc_rule_and_readiness_follows(mem: Mem) -> None:
    """Seen live: "12th year is 2025" was typed, but nothing could take it."""
    from app.agent.tools import run_tool

    mem.profile["hsc_year"] = 2023
    mem.doc("ssc_marksheet", ssc_year="2023")
    mem.profile["ssc_year"] = 2023
    checks.run_checks(None, UID, SESSION, include_missing=False)
    flag = next(f for f in mem.flags if f["reason_code"] == "hsc_before_ssc")
    assert checks.flag_card(flag, "en")[1]["can_type"]
    assert not checks.readiness(None, UID, SESSION)["ready"]
    args = {"flag_id": flag["id"], "new_value": "2025", "reason": "I passed 12th in 2025"}
    assert run_tool(_ctx(input_mode="text"), "resolve_flag", args).ok
    assert checks.run_checks(None, UID, SESSION, include_missing=False) == []
    ready = checks.readiness(None, UID, SESSION)
    assert ready["ready"]
    hsc = next(f for f in ready["fields"] if f["field_key"] == "hsc_year")
    assert (hsc["value"], hsc["source"], hsc["confirmed"]) == ("2025", "Your earlier choice", True)


def test_readiness_lists_every_value_with_a_source(mem: Mem) -> None:
    demo_docs(mem)
    checks.run_checks(None, UID, SESSION, include_missing=False)
    r = checks.readiness(None, UID, SESSION)
    assert not r["ready"] and len(r["open_block"]) == 1 and len(r["open_warn"]) == 1
    assert r["fields"] and all(f["source"] for f in r["fields"])


def test_picking_the_flagged_spelling_does_not_reraise(mem: Mem) -> None:
    """Seen live: confirming the passbook's own spelling raised the same flag again."""
    demo_docs(mem)
    checks.run_checks(None, UID, SESSION, include_missing=False)
    flag = next(f for f in mem.flags if f["field_key"] == "account_holder_name")
    pick = next(c for c in flag["details"]["candidates"] if c["value"] == "AARV SUNIL PATIL")
    checks.resolve(
        None,
        UID,
        SID,
        flag["id"],
        reason="bank spelling, fixing it",
        via="voice",
        candidate_id=pick["id"],
    )
    assert checks.run_checks(None, UID, SESSION, include_missing=True) == []


def test_a_typed_value_must_be_in_the_users_words(mem: Mem) -> None:
    """Guardrail 2 (found by /guardrails): the model must not put words in the user's mouth."""
    from app.agent.tools import run_tool

    mem.profile["hsc_year"] = 2023
    mem.doc("ssc_marksheet", ssc_year="2023")
    mem.profile["ssc_year"] = 2023
    checks.run_checks(None, UID, SESSION, include_missing=False)
    flag = next(f for f in mem.flags if f["reason_code"] == "hsc_before_ssc")
    args = {"flag_id": flag["id"], "new_value": "2026", "reason": "I passed 12th in 2025"}
    assert "what the user said" in run_tool(_ctx(input_mode="text"), "resolve_flag", args).error
    assert flag["status"] == "open"


def test_readiness_keeps_the_aadhaar_reading_for_as_per_aadhaar_boxes(mem: Mem) -> None:
    mem.doc("ssc_marksheet", full_name="KASLIWAL HARSH")
    rows = {f["field_key"]: f for f in checks.readiness(None, UID, SESSION)["fields"]}
    assert rows["full_name"]["on_aadhaar"] is None  # no Aadhaar read: nothing stands in for it
    mem.doc("aadhaar", full_name="Harsh Padam Kasliwal")
    rows = {f["field_key"]: f for f in checks.readiness(None, UID, SESSION)["fields"]}
    assert rows["full_name"]["on_aadhaar"] == "Harsh Padam Kasliwal"


def test_readiness_finds_the_english_twin_of_a_devanagari_name(mem: Mem) -> None:
    mem.doc("aadhaar", full_name="कार्तिक दिलीप कोकाटे")
    mem.doc("ssc_marksheet", full_name="Kartik Kokate")  # a word missing: not the same name
    rows = {f["field_key"]: f for f in checks.readiness(None, UID, SESSION)["fields"]}
    assert "in_english" not in rows["full_name"]
    mem.doc("hsc_marksheet", full_name="KARTIK DILIP KOKATE")
    rows = {f["field_key"]: f for f in checks.readiness(None, UID, SESSION)["fields"]}
    assert rows["full_name"]["in_english"] == "KARTIK DILIP KOKATE"
    assert rows["full_name"]["in_english_source"].startswith("Class 12 marksheet")


def test_answer_requirement_tool_needs_the_users_words(
    mem: Mem, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Guardrails 2/3: a guessed "no" would silently make a required document "not needed".
    from types import SimpleNamespace

    from app.agent.tools import Ctx, run_tool
    from tests.test_requirements import HOSTEL

    monkeypatch.setattr(checks, "usable_packs", lambda: {"demo.hostel": HOSTEL})
    session = {"id": SID, "scheme_key": "demo.hostel", "phase": "documents"}

    def ctx(text: str, message_id: str | None = "m9") -> Ctx:
        return Ctx(
            db=SimpleNamespace(), user_id=UID, session=session, lang="mr",
            message_id=message_id, input_mode="voice", user_text=text,
        )  # fmt: skip

    args = {"question_id": "hosteller", "answer": "no", "user_words": "नाही, मी घरी राहतो"}
    assert not run_tool(ctx("हो"), "answer_requirement", args).ok  # not what they said
    assert not run_tool(ctx("नाही, मी घरी राहतो", None), "answer_requirement", args).ok
    assert mem.fields == []
    res = run_tool(ctx("नाही, मी घरी राहतो"), "answer_requirement", args)
    assert res.ok and res.card.kind == "document_checklist"
    [answer] = [f for f in mem.fields if f["field_key"] == "answers.hosteller"]
    assert (answer["value"], answer["source_type"]) == ("no", "voice")
    assert answer["source_ref"]["message_id"] == "m9"
    items = {i["id"]: i for i in res.card.payload["items"]}
    assert items["hostel_certificate"]["need"] == "not_needed"
