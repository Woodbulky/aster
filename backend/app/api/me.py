from datetime import date
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    field_validator,
)

from app.db import supabase as repo
from app.deps import Db, UserId

router = APIRouter(prefix="/api")

Text = Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)]
Lang = Literal["mr", "hi", "en"]


class AssistantIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    avatar_id: Literal["aster", "mitra", "tara", "chintu"]
    assistant_name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)
    ]
    language: Lang
    voice: Text | None = None


class ProfileIn(BaseModel):
    """Values the user typed in the profile form (source = manual). No full Aadhaar or bank
    numbers can come in: unknown keys are rejected and Aadhaar is last-4 only (guardrail 6)."""

    model_config = ConfigDict(extra="forbid")
    full_name: Text | None = None
    full_name_local: Text | None = None
    dob: date | None = None
    gender: Text | None = None
    mobile: Annotated[str, StringConstraints(pattern=r"^\+?[0-9]{10,13}$")] | None = None
    domicile_state: Text | None = None
    district: Text | None = None
    taluka: Text | None = None
    category: Text | None = None
    caste: Text | None = None
    religion: Text | None = None
    annual_family_income: Annotated[float, Field(ge=0)] | None = None
    ssc_board: Text | None = None
    ssc_year: Annotated[int, Field(ge=1950, le=2100)] | None = None
    ssc_percentage: Annotated[float, Field(ge=0, le=100)] | None = None
    hsc_board: Text | None = None
    hsc_year: Annotated[int, Field(ge=1950, le=2100)] | None = None
    hsc_percentage: Annotated[float, Field(ge=0, le=100)] | None = None
    current_course: Text | None = None
    current_year: Annotated[int, Field(ge=1, le=10)] | None = None
    institute_name: Text | None = None
    aadhaar_last4: Annotated[str, StringConstraints(pattern=r"^[0-9]{4}$")] | None = None

    @field_validator("*", mode="before")
    @classmethod
    def _blank_is_none(cls, v: Any) -> Any:
        # The web form sends strings; "" means "not provided".
        return None if isinstance(v, str) and not v.strip() else v


@router.get("/me")
def me(db: Db, user_id: UserId) -> dict[str, Any]:
    # profiles only ever holds aadhaar_last4, never a full number, so nothing more to mask.
    return {"profile": repo.get_profile(db, user_id), "assistant": repo.get_assistant(db, user_id)}


@router.put("/assistant")
def put_assistant(body: AssistantIn, db: Db, user_id: UserId) -> dict[str, Any]:
    row = repo.upsert_assistant(db, user_id, body.model_dump())
    if not row:
        raise HTTPException(500, "assistant settings not saved")
    return row


@router.put("/profile")
def put_profile(body: ProfileIn, db: Db, user_id: UserId) -> dict[str, Any]:
    values = body.model_dump(mode="json", exclude_none=True)
    # The form re-sends every field: only changed ones become `manual`, so values confirmed in
    # conversation keep their text source + proposal link (guardrail 2).
    current = repo.get_profile(db, user_id) or {}
    values = {k: v for k, v in values.items() if current.get(k) != v}
    row = repo.update_profile(db, user_id, values, source_type="manual")
    if not row:
        raise HTTPException(404, "profile not found")
    return row


class ConfirmIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    proposal_id: UUID
    accept: bool
    edits: dict[str, Any] | None = None  # proposed keys the user corrected in the card


@router.post("/profile/confirm")
def confirm_profile(body: ConfirmIn, db: Db, user_id: UserId) -> dict[str, Any]:
    """Guardrail 4: conversation values reach the profile only through this. Values the user
    kept carry the proposal's evidence; values they corrected in the card are `manual`."""
    prop = repo.get_pending_proposal(db, user_id, str(body.proposal_id))
    if not prop:
        raise HTTPException(404, "proposal not found or already answered")
    audit = {"proposal_id": prop["id"]}
    if not body.accept:
        repo.set_proposal_status(db, user_id, prop["id"], "rejected")
        repo.write_audit(db, user_id, prop["session_id"], "profile.rejected", audit, actor="user")
        return {"status": "rejected", "saved": {}}
    edits = body.edits or {}
    if set(edits) - set(prop["updates"]):
        raise HTTPException(422, "edits may only change proposed fields")
    try:
        proposed = ProfileIn.model_validate(prop["updates"]).model_dump(
            mode="json", exclude_none=True
        )
        # exclude_unset keeps blanked fields as None = "don't save this one"
        edited = ProfileIn.model_validate(edits).model_dump(mode="json", exclude_unset=True)
    except ValidationError as e:
        raise HTTPException(422, e.errors(include_url=False, include_context=False)) from e
    kept = {k: v for k, v in proposed.items() if k not in edited or edited[k] == v}
    changed = {k: v for k, v in edited.items() if v is not None and v != proposed.get(k)}
    ref = {"proposal_id": prop["id"], "message_id": prop["message_id"]}
    repo.update_profile(db, user_id, kept, source_type=prop["evidence"], source_ref=ref)
    repo.update_profile(db, user_id, changed, source_type="manual", source_ref=ref)
    repo.set_proposal_status(db, user_id, prop["id"], "accepted")
    # Field names only: values stay in profiles, not in the audit trail.
    audit |= {"fields": sorted(kept), "edited": sorted(changed)}
    repo.write_audit(db, user_id, prop["session_id"], "profile.confirmed", audit, actor="user")
    return {"status": "accepted", "saved": kept | changed}
