from typing import Annotated, Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, HttpUrl, StringConstraints

from app.db import supabase as repo
from app.deps import Db, UserId

router = APIRouter(prefix="/api/sessions")

Key = Annotated[str, StringConstraints(strip_whitespace=True, max_length=100)]


class SessionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    portal: Key | None = None
    scheme_key: Key | None = None
    portal_url: HttpUrl | None = None


@router.post("", status_code=201)
def create_session(body: SessionIn, db: Db, user_id: UserId) -> dict[str, Any]:
    row = repo.create_session(db, user_id, body.model_dump(mode="json", exclude_none=True))
    if not row:
        raise HTTPException(500, "session not created")
    return row
