"""M8: audit chain verification, consent gates, delete my data, flag -> profile proposal."""

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.audit import row_hash, verify_all, verify_chain
from app.db import supabase as repo
from app.deps import get_db
from app.main import app
from app.verify.checks import propose_profile_update
from tests.test_api import AUTH, get_user


# ---------- audit chain ----------
def chain(n: int) -> list[dict[str, Any]]:
    rows, prev = [], "GENESIS"
    for i in range(1, n + 1):
        r = {
            "id": i,
            "user_id": "u1",
            "session_id": "s1",
            "actor": "user",
            "action": "flag.resolved",
            "prev_hash": prev,
            "payload_text": f'{{"flag_id": "f{i}"}}',
            "created_text": f"2026-10-04 10:00:0{i}.000000+00",
        }
        r["hash"] = prev = row_hash(r)
        rows.append(r)
    return rows


def test_verify_chain_ok_and_any_order() -> None:
    rows = chain(4)
    assert verify_chain(rows) == []
    assert verify_chain(rows[::-1]) == []


def test_verify_chain_flags_an_edited_payload() -> None:
    rows = chain(4)
    rows[1]["payload_text"] = '{"flag_id": "forged"}'
    assert verify_chain(rows) == [2]  # only the edited row: later links still match stored hashes


def test_verify_chain_flags_a_deleted_row() -> None:
    rows = chain(4)
    del rows[2]
    assert verify_chain(rows) == [4]


def test_verify_all_splits_chains() -> None:
    other = [{**r, "session_id": None} for r in chain(2)]
    assert verify_all(chain(3) + other) == {("u1", "s1"): [], ("u1", None): []}


def test_matches_the_db_trigger_formula() -> None:
    # Row 1 of the live chain (audit_events id 1, read with the same casts): the Python hash
    # equals the one the trigger stored.
    r = {
        "prev_hash": "GENESIS",
        "actor": "user",
        "action": "profile.confirmed",
        "payload_text": '{"edited": [], "fields": ["district", "dob", "full_name", "gender"], '
        '"proposal_id": "ab7e1f37-b370-40c8-b26c-9de76c339c2e"}',
        "created_text": "2026-10-02 21:18:20.085341+00",
    }
    assert row_hash(r) == "3b8778ff612ce6498750637eb974305e27fedf4ec8f736f3fbe80d06b1c2e451"


# ---------- consent gates + delete ----------
@pytest.fixture
def m8(monkeypatch: pytest.MonkeyPatch):
    st = SimpleNamespace(consent=None, calls=[])

    def rec(name: str, result: Any = None):
        def f(*a: Any, **_kw: Any) -> Any:
            st.calls.append((name, a[1:]))
            return result

        return f

    monkeypatch.setattr(repo, "latest_consent", lambda _db, _u, scope: st.consent)
    monkeypatch.setattr(repo, "get_profile", rec("get_profile", {"id": "u1"}))
    monkeypatch.setattr(repo, "update_profile", rec("update_profile", {"id": "u1"}))
    monkeypatch.setattr(repo, "write_audit", rec("write_audit"))
    monkeypatch.setattr(repo, "add_consent", rec("add_consent", {"id": "c1"}))
    monkeypatch.setattr(repo, "delete_user", rec("delete_user", 3))
    monkeypatch.setattr(repo, "get_session", lambda _db, u, s: {"id": s, "user_id": u})
    monkeypatch.setattr(repo, "get_document", rec("get_document"))
    app.dependency_overrides[get_db] = lambda: SimpleNamespace(
        auth=SimpleNamespace(get_user=get_user)
    )
    try:
        yield TestClient(app), st
    finally:
        app.dependency_overrides.clear()


def test_sensitive_profile_fields_need_consent(m8) -> None:
    c, st = m8
    r = c.put("/api/profile", json={"caste": "Maratha"}, headers=AUTH)
    assert r.status_code == 403 and r.json()["detail"] == "consent_required:sensitive_profile"
    assert not any(n == "update_profile" for n, _ in st.calls)
    # other fields don't need it
    assert c.put("/api/profile", json={"district": "Pune"}, headers=AUTH).status_code == 200
    st.consent = {"granted": False}  # a refusal is not consent
    assert c.put("/api/profile", json={"religion": "x"}, headers=AUTH).status_code == 403
    st.consent = {"granted": True}
    assert c.put("/api/profile", json={"caste": "Maratha"}, headers=AUTH).status_code == 200


def test_documents_need_consent(m8) -> None:
    c, st = m8
    body = {
        "document_id": "00000000-0000-0000-0000-0000000000d1",
        "doc_type": "income_certificate",
        "mime": "application/pdf",
    }
    path = "/api/sessions/00000000-0000-0000-0000-000000000001/documents"
    r = c.post(path, json=body, headers=AUTH)
    assert r.status_code == 403 and r.json()["detail"] == "consent_required:documents"
    assert not any(n == "get_document" for n, _ in st.calls)  # nothing read before consent


def test_consent_is_recorded_with_version_and_audited(m8) -> None:
    c, st = m8
    r = c.post("/api/consents", json={"scope": "documents", "granted": True}, headers=AUTH)
    assert r.status_code == 201
    (_, (uid, values)), (_, audit) = st.calls
    assert uid == "u1" and values["scope"] == "documents" and values["explanation_version"]
    assert audit[2] == "consent.recorded"
    bad = {"scope": "everything", "granted": True}
    assert c.post("/api/consents", json=bad, headers=AUTH).status_code == 422


def test_delete_me_deletes_the_callers_data(m8) -> None:
    c, st = m8
    r = c.delete("/api/me", headers=AUTH)
    assert r.status_code == 200 and r.json() == {"deleted": True, "files": 3}
    assert st.calls == [("delete_user", ("u1",))]
    assert c.delete("/api/me").status_code == 401


def fake_storage(files: list[str], removes: bool = True):
    log: list[Any] = []

    class Bucket:
        def list_v2(self, opts: dict) -> Any:
            hits = [f for f in files if f.startswith(opts["prefix"])][: opts["limit"]]
            return SimpleNamespace(objects=[SimpleNamespace(name=f) for f in hits])

        def remove(self, names: list[str]) -> None:
            log.append(("remove", list(names)))
            if removes:
                for n in names:
                    files.remove(n)

    db = SimpleNamespace(
        storage=SimpleNamespace(from_=lambda _b: Bucket()),
        auth=SimpleNamespace(
            admin=SimpleNamespace(delete_user=lambda uid: log.append(("delete_user", uid)))
        ),
    )
    return db, log


def test_delete_user_removes_every_file_then_the_account() -> None:
    files = ["u1/s1/d1.pdf", "u1/s1/d1/p1.png", "u1/general/aadhaar/1.jpg", "u2/s9/x.pdf"]
    db, log = fake_storage(files)
    assert repo.delete_user(db, "u1") == 3
    assert files == ["u2/s9/x.pdf"]  # another user's files untouched
    assert log[-1] == ("delete_user", "u1")


def test_delete_user_keeps_the_account_if_files_stay() -> None:
    db, log = fake_storage(["u1/a.pdf"], removes=False)
    with pytest.raises(RuntimeError):
        repo.delete_user(db, "u1")
    assert ("delete_user", "u1") not in log


# ---------- resolved flag -> profile proposal (guardrail 4) ----------
def flag(**kw: Any) -> dict[str, Any]:
    base = {
        "id": "f1",
        "session_id": "s1",
        "status": "resolved",
        "field_key": "annual_family_income",
        "details": {
            "candidates": [
                {
                    "id": "c1",
                    "field_key": "annual_family_income",
                    "value": "1,48,000",
                    "source_type": "document",
                },
                {
                    "id": "c2",
                    "field_key": "annual_family_income",
                    "value": "120000",
                    "source_type": "profile",
                },
            ]
        },
        "resolution": {
            "candidate_id": "c1",
            "value": "1,48,000",
            "field_value_id": "fv1",
            "via": "tap",
            "message_id": None,
        },
    }
    return base | kw


@pytest.fixture
def props(store, monkeypatch: pytest.MonkeyPatch):
    store.profile.update({"annual_family_income": 120000})
    return store


def test_resolution_proposes_the_picked_document_value(props) -> None:
    p = propose_profile_update(None, "u1", flag())
    assert p["updates"] == {"annual_family_income": 148000.0}
    assert p["evidence"] == "document" and p["status"] == "pending"
    assert p["source_ref"] == {"flag_id": "f1", "field_value_id": "fv1"}
    assert props.profile["annual_family_income"] == 120000  # nothing saved before the card


def test_no_proposal_when_nothing_changes(props) -> None:
    same = flag(resolution={"candidate_id": "c2", "value": "120000", "field_value_id": "fv2"})
    assert propose_profile_update(None, "u1", same) is None
    assert propose_profile_update(None, "u1", flag(status="acknowledged")) is None
    assert propose_profile_update(None, "u1", flag(field_key="bank_ifsc", details={})) is None
    assert props.proposals == []


def test_typed_voice_value_is_voice_evidence(props) -> None:
    res = {
        "candidate_id": None,
        "value": "150000",
        "field_value_id": "fv3",
        "via": "voice",
        "message_id": "m7",
    }
    p = propose_profile_update(None, "u1", flag(resolution=res))
    assert p["evidence"] == "voice" and p["message_id"] == "m7"
    assert p["updates"] == {"annual_family_income": 150000.0}


def test_one_proposal_per_flag(props) -> None:
    assert propose_profile_update(None, "u1", flag()) is not None
    assert propose_profile_update(None, "u1", flag()) is None  # flag_resolved sent twice
    assert len(props.proposals) == 1


def test_vault_falls_back_to_a_document_read_in_another_application(m8, monkeypatch) -> None:
    c, st = m8
    st.consent = {"granted": True}
    copies: list[tuple[str, str]] = []
    bucket = SimpleNamespace(list=lambda _f: [], copy=lambda a, b: copies.append((a, b)))
    app.dependency_overrides[get_db] = lambda: SimpleNamespace(
        auth=SimpleNamespace(get_user=get_user), storage=SimpleNamespace(from_=lambda _b: bucket)
    )
    monkeypatch.setattr("app.api.documents.process_document", lambda *a: None)
    monkeypatch.setattr(repo, "list_documents", lambda *a, **kw: [])
    monkeypatch.setattr(repo, "add_document", lambda *a: {"id": "d"})
    prev = {"storage_path": "u1/old/x.pdf", "mime": "application/pdf"}
    monkeypatch.setattr(repo, "latest_read_document", lambda _db, u, t, s: prev)
    path = "/api/sessions/00000000-0000-0000-0000-000000000002/documents/from-vault"
    r = c.post(path, json={"doc_type": "aadhaar"}, headers=AUTH)
    assert r.status_code == 202 and copies[0][0] == "u1/old/x.pdf"
    assert copies[0][1].startswith("u1/00000000-0000-0000-0000-000000000002/")
    monkeypatch.setattr(repo, "latest_read_document", lambda *a: None)
    assert c.post(path, json={"doc_type": "aadhaar"}, headers=AUTH).status_code == 404


def test_vault_reuses_the_masked_pages_of_a_deleted_id_original(m8, monkeypatch) -> None:
    # seen live: the Aadhaar original is deleted after reading (guardrail 6); copying it failed
    from storage3.exceptions import StorageApiError

    c, st = m8
    st.consent = {"granted": True}
    copies: list[tuple[str, str]] = []

    def copy(a: str, b: str) -> None:
        if a.endswith(".pdf"):
            raise StorageApiError("not found", "NoSuchKey", 404)
        copies.append((a, b))

    def ls(folder: str) -> list[dict]:
        return [{"name": "p1.png"}, {"name": "p2.png"}] if folder == "u1/old/x" else []

    bucket = SimpleNamespace(list=ls, copy=copy)
    app.dependency_overrides[get_db] = lambda: SimpleNamespace(
        auth=SimpleNamespace(get_user=get_user), storage=SimpleNamespace(from_=lambda _b: bucket)
    )
    monkeypatch.setattr("app.api.documents.process_document", lambda *a: None)
    monkeypatch.setattr(repo, "list_documents", lambda *a, **kw: [])
    monkeypatch.setattr(repo, "add_document", lambda *a: {"id": "d"})
    prev = {"storage_path": "u1/old/x.pdf", "mime": "application/pdf"}
    monkeypatch.setattr(repo, "latest_read_document", lambda *a: prev)
    path = "/api/sessions/00000000-0000-0000-0000-000000000002/documents/from-vault"
    r = c.post(path, json={"doc_type": "aadhaar"}, headers=AUTH)
    new = r.json()["document_id"]
    assert r.status_code == 202
    assert [b for _, b in copies] == [
        f"u1/00000000-0000-0000-0000-000000000002/{new}/p1.png",
        f"u1/00000000-0000-0000-0000-000000000002/{new}/p2.png",
    ]
