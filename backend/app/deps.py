from typing import Annotated

from fastapi import Depends, Header, HTTPException
from supabase import Client
from supabase_auth.errors import AuthError

from app.db.supabase import get_db

Db = Annotated[Client, Depends(get_db)]


def user_from_token(db: Client, token: str) -> str | None:
    """user_id from a Supabase access token, verified by Supabase Auth on every call."""
    try:
        res = db.auth.get_user(token)
    except AuthError:
        return None
    return res.user.id if res and res.user else None


def current_user(db: Db, authorization: Annotated[str | None, Header()] = None) -> str:
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(401, "missing bearer token")
    user_id = user_from_token(db, token)
    if not user_id:
        raise HTTPException(401, "invalid token")
    return user_id


UserId = Annotated[str, Depends(current_user)]
