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


