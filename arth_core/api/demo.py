"""Sample-data controls + the read endpoints the Funds and Arth Raksha pages use."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import demo
from ..db import get_db
from ..deps import get_current_user
from ..models import BankAccount, BankConnection, User

router = APIRouter(tags=["demo", "bank", "crypto"])


@router.get("/demo/status")
def status(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return {"active": demo.is_active(db, user)}


@router.post("/demo/seed")
def seed(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return {"loaded": demo.seed_demo(db, user), "active": True}


@router.delete("/demo")
def clear(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    demo.clear_demo(db, user)
    return {"active": False}


@router.get("/bank/accounts")
def accounts(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.execute(select(BankAccount, BankConnection).join(
        BankConnection, BankAccount.connection_id == BankConnection.id).where(
        BankAccount.user_id == user.id).order_by(BankAccount.name)).all()
    items = [{
        "id": a.id, "name": a.name, "mask": a.mask, "type": a.type, "currency": a.currency,
        "balance": float(a.balance) if a.balance is not None else None,
        "institution": c.institution_name, "data_mode": "demo" if c.provider == "demo" else "live",
        "last_synced_at": c.last_synced_at.isoformat() if c.last_synced_at else None,
    } for a, c in rows]
    known = [i["balance"] for i in items if i["balance"] is not None]
    return {"accounts": items, "total_balance": sum(known) if known else None}


@router.get("/crypto/overview")
def crypto_overview(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    data = demo.crypto_demo(db, user)
    return data or {"connected": False}
