"""Wallet sign-in, linked wallets, and the real on-chain portfolio endpoints.
Address-only and read-only: no endpoint accepts or stores a key or seed phrase."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import crypto, demo, wallet_auth
from ..db import get_db
from ..deps import get_current_user
from ..models import User, WalletLink
from ..security import issue_user_tokens
from .auth import user_out

router = APIRouter(tags=["crypto"])


class NonceRequest(BaseModel):
    address: str
    domain: str = Field(default="", max_length=100)


class VerifyRequest(BaseModel):
    address: str
    signature: str = Field(min_length=10, max_length=400)
    token: str = Field(max_length=4000)


class WatchRequest(BaseModel):
    address: str
    label: str = Field(default="", max_length=80)


def _short(a: str) -> str:
    return f"{a[:6]}…{a[-4:]}"


# ---- sign in with a wallet ------------------------------------------------
@router.post("/auth/wallet/nonce")
def wallet_nonce(req: NonceRequest):
    try:
        return wallet_auth.make_challenge(req.address, req.domain)
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@router.post("/auth/wallet/verify")
def wallet_verify(req: VerifyRequest, db: Session = Depends(get_db)):
    """Log in (or sign up) with a wallet signature. The first sign-in creates an account
    bound to this address; later sign-ins return to it."""
    try:
        addr = wallet_auth.verify_challenge(req.address, req.signature, req.token)
    except ValueError as exc:
        raise HTTPException(401, str(exc))
    link = db.scalar(select(WalletLink).where(
        WalletLink.address == addr, WalletLink.chain == "ethereum", WalletLink.verified.is_(True)))
    if link:
        user = db.get(User, link.user_id)
    else:
        # "!" is not a valid scrypt hash, so this account can never be opened with a password.
        user = User(email=f"{addr}@wallet.local", name=_short(addr), password_hash="!wallet-login")
        db.add(user)
        db.flush()
        db.add(WalletLink(user_id=user.id, address=addr, chain="ethereum", label="My wallet", verified=True))
        db.commit()
    return {"user": user_out(user), **issue_user_tokens(user.id)}


# ---- linked wallets --------------------------------------------------------
def _wallet_out(w: WalletLink) -> dict:
    return {"id": w.id, "address": w.address, "label": w.label, "chain": w.chain,
            "verified": w.verified, "demo": w.chain == "demo"}


def _mine(db: Session, user: User, wallet_id: str) -> WalletLink:
    w = db.get(WalletLink, wallet_id)
    if w is None or w.user_id != user.id:
        raise HTTPException(404, "Wallet not found.")
    return w


@router.get("/crypto/wallets")
def list_wallets(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(WalletLink).where(WalletLink.user_id == user.id).order_by(WalletLink.created_at)).all()
    return {"wallets": [_wallet_out(w) for w in rows]}


@router.post("/crypto/wallets/watch", status_code=201)
def watch_wallet(req: WatchRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Track any public address read-only (no ownership proof)."""
    try:
        addr = crypto.normalize_address(req.address)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    w = db.scalar(select(WalletLink).where(
        WalletLink.user_id == user.id, WalletLink.address == addr, WalletLink.chain == "ethereum"))
    if w is None:
        w = WalletLink(user_id=user.id, address=addr, chain="ethereum", label=req.label.strip() or "Watched wallet", verified=False)
        db.add(w)
        db.commit()
    return _wallet_out(w)


@router.post("/crypto/wallets/link", status_code=201)
def link_wallet(req: VerifyRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Attach a wallet you control (proved by signature) to the signed-in account."""
    try:
        addr = wallet_auth.verify_challenge(req.address, req.signature, req.token)
    except ValueError as exc:
        raise HTTPException(401, str(exc))
    other = db.scalar(select(WalletLink).where(
        WalletLink.address == addr, WalletLink.chain == "ethereum",
        WalletLink.verified.is_(True), WalletLink.user_id != user.id))
    if other:
        raise HTTPException(409, "This wallet is already linked to another ArthDrishti account.")
    w = db.scalar(select(WalletLink).where(
        WalletLink.user_id == user.id, WalletLink.address == addr, WalletLink.chain == "ethereum"))
    if w is None:
        w = WalletLink(user_id=user.id, address=addr, chain="ethereum", label="My wallet")
        db.add(w)
    w.verified = True
    db.commit()
    return _wallet_out(w)


@router.delete("/crypto/wallets/{wallet_id}", status_code=204)
def remove_wallet(wallet_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    w = _mine(db, user, wallet_id)
    if user.email.endswith("@wallet.local") and w.verified and w.chain == "ethereum":
        raise HTTPException(409, "This is the wallet you sign in with, so it can't be removed.")
    db.delete(w)
    db.commit()


# ---- portfolio -------------------------------------------------------------
def _pick(db: Session, user: User, wallet_id: Optional[str]) -> Optional[WalletLink]:
    if wallet_id:
        return _mine(db, user, wallet_id)
    rows = db.scalars(select(WalletLink).where(WalletLink.user_id == user.id).order_by(WalletLink.created_at)).all()
    live = [w for w in rows if w.chain != "demo"]
    return (live or rows or [None])[0]        # a real wallet wins over sample data


@router.get("/crypto/overview")
def overview(wallet_id: Optional[str] = None, refresh: bool = False,
             user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    w = _pick(db, user, wallet_id)
    if w is None:
        return {"connected": False}
    if w.chain == "demo":
        data = demo.crypto_demo(db, user)
        return {**data, "wallet_id": w.id}
    try:
        data = crypto.get_overview(w.address, verified_owner=w.verified, force=refresh)
    except crypto.ChainDataError as exc:
        raise HTTPException(502, detail={"message": f"Couldn't read blockchain data right now. {exc}", "retryable": True})
    return {**data, "wallet_id": w.id, "label": w.label}


@router.get("/crypto/performance")
def performance(wallet_id: Optional[str] = None, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    w = _pick(db, user, wallet_id)
    if w is None or w.chain == "demo":
        return {"available": False, "reason": "Performance history is only available for real wallets."}
    try:
        return crypto.get_performance(w.address, verified_owner=w.verified)
    except crypto.ChainDataError as exc:
        return {"available": False, "reason": f"Price history is unavailable right now. {exc}"}
