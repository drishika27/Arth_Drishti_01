"""FastAPI dependencies shared by every user-scoped router."""
from __future__ import annotations

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from shared_engine.auth import decode_jwt
from .db import get_db
from .models import User

_bearer = HTTPBearer(
    scheme_name="ArthDrishtiUser",
    description="Access token from POST /auth/login or /auth/register.",
)


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    try:
        payload = decode_jwt(credentials.credentials)
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Session expired — please sign in again.")
    except jwt.InvalidTokenError:
        raise HTTPException(401, "Invalid token.")
    if payload.get("typ") != "user":
        raise HTTPException(401, "Invalid token.")
    user = db.get(User, payload.get("sub"))
    if user is None:
        raise HTTPException(401, "Account no longer exists.")
    return user
