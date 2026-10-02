from datetime import date
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

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
    row = repo.update_profile(db, user_id, values, source_type="manual")
    if not row:
        raise HTTPException(404, "profile not found")
    return row
