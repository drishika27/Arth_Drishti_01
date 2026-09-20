"""Account endpoints: register, login, refresh, profile/preferences."""
from __future__ import annotations

import re
from decimal import Decimal
from typing import Literal, Optional

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from shared_engine.auth import decode_jwt
from ..db import get_db
from ..deps import get_current_user
from ..models import User
from ..security import hash_password, verify_password, issue_user_tokens, login_limiter

router = APIRouter(tags=["account"])

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _norm_email(v: str) -> str:
    v = v.strip().lower()
    if len(v) > 255 or not _EMAIL_RE.match(v):
        raise ValueError("Enter a valid email address.")
    return v


class RegisterRequest(BaseModel):
    email: str
    password: str = Field(min_length=8, max_length=128)
    name: str = Field(default="", max_length=120)

    @field_validator("email")
    @classmethod
    def _check_email(cls, v: str) -> str:
        return _norm_email(v)


class LoginRequest(BaseModel):
    email: str
    password: str = Field(max_length=128)

    @field_validator("email")
    @classmethod
    def _check_email(cls, v: str) -> str:
        return _norm_email(v)


class RefreshRequest(BaseModel):
    refresh_token: str


class ProfileUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=120)
    language: Optional[Literal["English", "हिंदी"]] = None
    currency: Optional[Literal["INR", "USD"]] = None
    # None = leave unchanged; 0 = clear the budget.
    monthly_budget: Optional[float] = Field(default=None, ge=0, le=1e10)


def user_out(u: User) -> dict:
    return {
        "id": u.id, "email": u.email, "name": u.name, "language": u.language,
        "currency": u.currency,
        "monthly_budget": float(u.monthly_budget) if u.monthly_budget is not None else None,
    }


@router.post("/auth/register", status_code=201)
def register(req: RegisterRequest, db: Session = Depends(get_db)):
    if req.email.endswith("@wallet.local"):
        # Reserved for wallet-only accounts; allowing it would let someone squat a wallet's account.
        raise HTTPException(422, "That email domain is reserved.")
    if db.scalar(select(User).where(User.email == req.email)):
        raise HTTPException(409, "An account with this email already exists.")
    user = User(email=req.email, name=req.name.strip(), password_hash=hash_password(req.password))
    db.add(user)
    db.commit()
    return {"user": user_out(user), **issue_user_tokens(user.id)}


@router.post("/auth/login")
def login(req: LoginRequest, request: Request, db: Session = Depends(get_db)):
    key = f"{req.email}|{request.client.host if request.client else '-'}"
    if login_limiter.blocked(key):
        raise HTTPException(429, "Too many failed attempts. Try again in a few minutes.")
    user = db.scalar(select(User).where(User.email == req.email))
    # Same message for unknown email and wrong password: no account enumeration.
    if user is None or not verify_password(req.password, user.password_hash):
        login_limiter.record_failure(key)
        raise HTTPException(401, "Incorrect email or password.")
    login_limiter.reset(key)
    return {"user": user_out(user), **issue_user_tokens(user.id)}


@router.post("/auth/refresh")
def refresh(req: RefreshRequest, db: Session = Depends(get_db)):
    try:
        payload = decode_jwt(req.refresh_token)
    except jwt.InvalidTokenError:
        raise HTTPException(401, "Invalid or expired refresh token.")
    if payload.get("typ") != "refresh" or db.get(User, payload.get("sub")) is None:
        raise HTTPException(401, "Invalid or expired refresh token.")
    return issue_user_tokens(payload["sub"])


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return user_out(user)


@router.patch("/me")
def update_me(req: ProfileUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if req.name is not None:
        user.name = req.name.strip()
    if req.language is not None:
        user.language = req.language
    if req.currency is not None:
        user.currency = req.currency
    if req.monthly_budget is not None:
        user.monthly_budget = Decimal(str(req.monthly_budget)) if req.monthly_budget > 0 else None
    db.add(user)
    db.commit()
    return user_out(user)
