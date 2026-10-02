from typing import Annotated

from fastapi import Depends, Header, HTTPException
from supabase import Client
from supabase_auth.errors import AuthError

from app.db.supabase import get_db

Db = Annotated[Client, Depends(get_db)]


def current_user(db: Db, authorization: Annotated[str | None, Header()] = None) -> str:
    """user_id from a Supabase access token, verified by Supabase Auth on every call."""
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(401, "missing bearer token")
    try:
        res = db.auth.get_user(token)
    except AuthError:
        res = None
    if not res or not res.user:
        raise HTTPException(401, "invalid token")
    return res.user.id


UserId = Annotated[str, Depends(current_user)]
