"""
The one expense system. Manual entries, OCR receipts and bank transactions
are all rows in `expenses`; this router is how the UI reads and corrects
them. Every query is scoped to the authenticated user.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..categorizer import CATEGORIES, categorize, learn_rule, load_user_rules, merchant_key
from ..db import get_db
from ..deps import get_current_user
from ..models import BankAccount, Expense, User

router = APIRouter(tags=["expenses"])

MAX_AMOUNT = 1_000_000_000


def _check_category(v: str) -> str:
    if v not in CATEGORIES:
        raise ValueError(f"category must be one of: {', '.join(CATEGORIES)}")
    return v


def _check_date(v: date) -> date:
    if v > date.today() + timedelta(days=1):
        raise ValueError("date cannot be in the future")
    if v < date(2000, 1, 1):
        raise ValueError("date is too far in the past")
    return v


class ExpenseCreate(BaseModel):
    merchant: str = Field(min_length=1, max_length=200)
    amount: float = Field(gt=0, lt=MAX_AMOUNT)
    tax: Optional[float] = Field(default=None, ge=0, lt=MAX_AMOUNT)
    category: Optional[str] = None            # omitted -> auto-categorized
    date: date
    note: str = Field(default="", max_length=500)
    kind: Literal["expense", "income"] = "expense"

    @field_validator("merchant")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("merchant cannot be blank")
        return v

    @field_validator("category")
    @classmethod
    def _cat(cls, v):
        return None if v is None else _check_category(v)

    @field_validator("date")
    @classmethod
    def _d(cls, v: date) -> date:
        return _check_date(v)


class ExpenseUpdate(BaseModel):
    merchant: Optional[str] = Field(default=None, min_length=1, max_length=200)
    amount: Optional[float] = Field(default=None, gt=0, lt=MAX_AMOUNT)
    tax: Optional[float] = Field(default=None, ge=0, lt=MAX_AMOUNT)
    category: Optional[str] = None
    date: Optional[date] = None
    note: Optional[str] = Field(default=None, max_length=500)
    # Re-apply a corrected category to the user's other, un-corrected
    # transactions from the same merchant.
    apply_to_similar: bool = False

    @field_validator("category")
    @classmethod
    def _cat(cls, v):
        return None if v is None else _check_category(v)

    @field_validator("date")
    @classmethod
    def _d(cls, v):
        return None if v is None else _check_date(v)


def expense_out(e: Expense, account_names: Optional[dict[str, str]] = None) -> dict:
    return {
        "id": e.id, "source": e.source, "kind": e.kind, "merchant": e.merchant,
        "amount": float(e.amount), "tax": float(e.tax) if e.tax is not None else None,
        "currency": e.currency, "category": e.category, "category_source": e.category_source,
        "date": e.date.isoformat(), "note": e.note, "account_id": e.account_id,
        "account_name": (account_names or {}).get(e.account_id) if e.account_id else None,
        "raw_description": e.raw_description, "user_edited": e.user_edited,
        "receipt_id": e.receipt_id,
    }


def _account_names(db: Session, user_id: str) -> dict[str, str]:
    rows = db.execute(select(BankAccount.id, BankAccount.name, BankAccount.mask)
                      .where(BankAccount.user_id == user_id)).all()
    return {r.id: f"{r.name} {r.mask}".strip() for r in rows}


def _owned(db: Session, user: User, expense_id: str) -> Expense:
    e = db.get(Expense, expense_id)
    # 404 (not 403) for other users' rows: don't reveal that the id exists.
    if e is None or e.user_id != user.id or e.ignored:
        raise HTTPException(404, "Expense not found.")
    return e


@router.get("/meta/categories")
def categories():
    return {"categories": CATEGORIES}


_fx_cache: dict = {"at": 0.0, "usd_per_inr": None}


@router.get("/meta/fx")
def fx_rate(user: User = Depends(get_current_user)):
    """Live INR->USD rate (frankfurter.app, ECB data, no key), cached 1h.
    503 when unavailable — the UI then keeps showing INR instead of using a made-up rate."""
    import time
    import httpx
    if _fx_cache["usd_per_inr"] and time.time() - _fx_cache["at"] < 3600:
        return {"usd_per_inr": _fx_cache["usd_per_inr"]}
    try:
        r = httpx.get("https://api.frankfurter.app/latest", params={"from": "INR", "to": "USD"}, timeout=8)
        r.raise_for_status()
        rate = float(r.json()["rates"]["USD"])
    except Exception:
        raise HTTPException(503, "Exchange rate is unavailable right now.")
    _fx_cache.update(at=time.time(), usd_per_inr=rate)
    return {"usd_per_inr": rate}


@router.get("/expenses")
def list_expenses(
    search: str = "", category: Optional[str] = None,
    source: Optional[Literal["manual", "ocr", "bank"]] = None,
    kind: Literal["expense", "income", "all"] = "expense",
    date_from: Optional[date] = None, date_to: Optional[date] = None,
    limit: int = Query(200, ge=1, le=500), offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    q = select(Expense).where(Expense.user_id == user.id, Expense.ignored.is_(False))
    if kind != "all":
        q = q.where(Expense.kind == kind)
    if category:
        q = q.where(Expense.category == category)
    if source:
        q = q.where(Expense.source == source)
    if date_from:
        q = q.where(Expense.date >= date_from)
    if date_to:
        q = q.where(Expense.date <= date_to)
    if search.strip():
        like = f"%{search.strip().lower()}%"
        q = q.where(or_(func.lower(Expense.merchant).like(like),
                        func.lower(Expense.category).like(like),
                        func.lower(Expense.note).like(like)))
    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    rows = db.scalars(q.order_by(Expense.date.desc(), Expense.created_at.desc())
                      .limit(limit).offset(offset)).all()
    names = _account_names(db, user.id)
    return {"items": [expense_out(e, names) for e in rows], "total": total}


@router.post("/expenses", status_code=201)
def create_expense(req: ExpenseCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if req.category:
        category, cat_src = req.category, "manual"
    else:
        category, src = categorize(req.merchant, "", load_user_rules(db, user.id))
        cat_src = "manual" if src == "none" else src
    e = Expense(
        user_id=user.id, source="manual", kind=req.kind, merchant=req.merchant,
        amount=Decimal(str(req.amount)), tax=Decimal(str(req.tax)) if req.tax is not None else None,
        currency=user.currency, category=category, category_source=cat_src,
        date=req.date, note=req.note.strip(),
    )
    db.add(e)
    db.commit()
    return expense_out(e)


@router.patch("/expenses/{expense_id}")
def update_expense(expense_id: str, req: ExpenseUpdate,
                   user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    e = _owned(db, user, expense_id)
    if req.merchant is not None:
        e.merchant = req.merchant.strip()
    if req.amount is not None:
        e.amount = Decimal(str(req.amount))
    if req.tax is not None:
        e.tax = Decimal(str(req.tax))
    if req.date is not None:
        e.date = req.date
    if req.note is not None:
        e.note = req.note.strip()
    changed_category = req.category is not None and req.category != e.category
    if req.category is not None:
        e.category = req.category
        e.category_source = "user"
    e.user_edited = True

    updated_similar = 0
    if changed_category:
        learn_rule(db, user.id, e.merchant, req.category)      # remembered for future imports
        if req.apply_to_similar:
            key = merchant_key(e.merchant)
            for other in db.scalars(select(Expense).where(
                    Expense.user_id == user.id, Expense.id != e.id,
                    Expense.ignored.is_(False), Expense.category_source != "user")):
                if merchant_key(other.merchant) == key:
                    other.category, other.category_source = req.category, "user_rule"
                    updated_similar += 1
    db.commit()
    return {**expense_out(e, _account_names(db, user.id)), "updated_similar": updated_similar}


@router.delete("/expenses/{expense_id}", status_code=204)
def delete_expense(expense_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    e = _owned(db, user, expense_id)
    if e.source == "bank":
        e.ignored = True        # keep the row so the next sync doesn't re-import it
    else:
        db.delete(e)
    db.commit()


# ---- aggregates for Dashboard / Funds / Analytics -------------------------
def _month_bounds(month: Optional[str]) -> tuple[date, date]:
    try:
        first = datetime.strptime(month, "%Y-%m").date() if month else date.today().replace(day=1)
    except ValueError:
        raise HTTPException(422, "month must look like YYYY-MM")
    nxt = (first.replace(day=28) + timedelta(days=4)).replace(day=1)
    return first, nxt


def _sum(db: Session, user_id: str, kind: str, start: date, end: date) -> float:
    v = db.scalar(select(func.coalesce(func.sum(Expense.amount), 0)).where(
        Expense.user_id == user_id, Expense.kind == kind, Expense.ignored.is_(False),
        Expense.date >= start, Expense.date < end))
    return float(v or 0)


@router.get("/expenses/summary")
def summary(month: Optional[str] = None, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    start, end = _month_bounds(month)
    prev_start = (start - timedelta(days=1)).replace(day=1)

    by_cat: dict[str, float] = defaultdict(float)
    for cat, amt in db.execute(select(Expense.category, func.sum(Expense.amount)).where(
            Expense.user_id == user.id, Expense.kind == "expense", Expense.ignored.is_(False),
            Expense.date >= start, Expense.date < end).group_by(Expense.category)):
        by_cat[cat] = float(amt)

    today = date.today()
    days = [today - timedelta(days=i) for i in range(6, -1, -1)]
    daily = {d: 0.0 for d in days}
    for d, amt in db.execute(select(Expense.date, func.sum(Expense.amount)).where(
            Expense.user_id == user.id, Expense.kind == "expense", Expense.ignored.is_(False),
            Expense.date >= days[0], Expense.date <= today).group_by(Expense.date)):
        daily[d] = float(amt)

    spend = _sum(db, user.id, "expense", start, end)
    prev_spend = _sum(db, user.id, "expense", prev_start, start)
    budget = float(user.monthly_budget) if user.monthly_budget is not None else None
    recent = db.scalars(select(Expense).where(
        Expense.user_id == user.id, Expense.kind == "expense", Expense.ignored.is_(False))
        .order_by(Expense.date.desc(), Expense.created_at.desc()).limit(5)).all()
    accounts = db.scalars(select(BankAccount).where(BankAccount.user_id == user.id)).all()
    balances = [a.balance for a in accounts if a.balance is not None]

    return {
        "month": start.strftime("%Y-%m"),
        "spend": spend, "income": _sum(db, user.id, "income", start, end),
        "previous_month_spend": prev_spend,
        "spend_change_pct": round((spend - prev_spend) / prev_spend * 100, 1) if prev_spend else None,
        "budget": budget,
        "remaining_budget": round(budget - spend, 2) if budget is not None else None,
        "categories": [{"category": c, "amount": a} for c, a in sorted(by_cat.items(), key=lambda x: -x[1])],
        "last_7_days": [{"date": d.isoformat(), "label": d.strftime("%a"), "amount": v} for d, v in daily.items()],
        "recent": [expense_out(e) for e in recent],
        "bank_accounts": len(accounts),
        # Only reported when at least one linked account really has a balance.
        "available_funds": float(sum(balances)) if balances else None,
    }
