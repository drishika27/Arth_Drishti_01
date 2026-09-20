"""
Bank endpoints.

  Connect a bank (consent flow):  providers -> connect/start -> (user approves) -> connect/complete
  Manage:                         connections, sync, disconnect, accounts
  Real data without an aggregator: statements/parse -> (user reviews) -> statements/import

Bank passwords, OTPs and UPI PINs are never requested: a provider returns only an opaque
access token, which is stored encrypted. Every query is scoped to the signed-in user.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Literal, Optional

import jwt
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from shared_engine.auth import decode_jwt, encode_jwt
from .. import statements
from ..bank import sync as bank_sync
from ..bank.providers import ProviderError, get_provider, registry
from ..categorizer import CATEGORIES, categorize, learn_rule, load_user_rules, normalize_merchant
from ..db import get_db
from ..deps import get_current_user
from ..models import BankAccount, BankConnection, Expense, User
from ..security import encrypt_secret

router = APIRouter(tags=["bank"])
CONSENT_TTL = 900
_STATEMENT_PROVIDER = "statement"
_MODE = {"demo": "demo", "sandbox": "sandbox", _STATEMENT_PROVIDER: "statement"}


def _conn_out(c: BankConnection) -> dict:
    return {
        "id": c.id, "provider": c.provider, "institution": c.institution_name, "status": c.status,
        "data_mode": _MODE.get(c.provider, "live"), "accounts": len(c.accounts),
        "last_synced_at": c.last_synced_at.isoformat() if c.last_synced_at else None, "last_error": c.last_error,
        "auto_sync": c.provider not in ("demo", _STATEMENT_PROVIDER),
    }


def _mine(db: Session, user: User, conn_id: str) -> BankConnection:
    c = db.get(BankConnection, conn_id)
    if c is None or c.user_id != user.id:
        raise HTTPException(404, "Bank connection not found.")
    return c


# ---- accounts / connections -------------------------------------------------
@router.get("/bank/accounts")
def accounts(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.execute(select(BankAccount, BankConnection).join(
        BankConnection, BankAccount.connection_id == BankConnection.id).where(
        BankAccount.user_id == user.id).order_by(BankAccount.name)).all()
    items = [{
        "id": a.id, "name": a.name, "mask": a.mask, "type": a.type, "currency": a.currency,
        "balance": float(a.balance) if a.balance is not None else None,
        "institution": c.institution_name, "connection_id": c.id, "data_mode": _MODE.get(c.provider, "live"),
        "last_synced_at": c.last_synced_at.isoformat() if c.last_synced_at else None,
    } for a, c in rows]
    known = [i["balance"] for i in items if i["balance"] is not None]
    return {"accounts": items, "total_balance": sum(known) if known else None}


@router.get("/bank/connections")
def connections(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(BankConnection).where(BankConnection.user_id == user.id)
                      .order_by(BankConnection.created_at)).all()
    return {"connections": [_conn_out(c) for c in rows]}


@router.get("/bank/providers")
def providers(user: User = Depends(get_current_user)):
    return {"providers": [{"id": p.id, "name": p.name, "mode": p.mode, "institutions": p.institutions()}
                          for p in registry().values()]}


# ---- consent flow -----------------------------------------------------------
class StartRequest(BaseModel):
    provider: str = "sandbox"
    institution_id: str


class CompleteRequest(BaseModel):
    consent_id: str = Field(max_length=2000)
    approve: bool = True


@router.post("/bank/connect/start")
def connect_start(req: StartRequest, user: User = Depends(get_current_user)):
    """Step 1: show the user exactly what will be shared, before anything is connected."""
    try:
        details = get_provider(req.provider).consent_details(req.institution_id)
    except (ProviderError, ValueError) as exc:
        raise HTTPException(422, str(exc))
    consent_id = encode_jwt({"typ": "bank_consent", "uid": user.id, "prov": req.provider, "inst": req.institution_id}, CONSENT_TTL)
    return {"consent_id": consent_id, "consent": details, "expires_in": CONSENT_TTL}


@router.post("/bank/connect/complete", status_code=201)
def connect_complete(req: CompleteRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Step 2: the user approved (or declined) on the consent screen."""
    try:
        claims = decode_jwt(req.consent_id)
    except jwt.InvalidTokenError:
        raise HTTPException(422, "This consent request expired. Please start again.")
    if claims.get("typ") != "bank_consent" or claims.get("uid") != user.id:
        raise HTTPException(422, "This consent request isn't valid.")
    if not req.approve:
        return {"connected": False, "message": "No problem — nothing was connected or shared."}
    try:
        provider = get_provider(claims["prov"])
        token = provider.grant_access(claims["inst"])
        institution = next((i["name"] for i in provider.institutions() if i["id"] == claims["inst"]), claims["inst"])
    except (ProviderError, ValueError) as exc:
        raise HTTPException(502, detail={"message": str(exc), "retryable": True})
    conn = BankConnection(user_id=user.id, provider=claims["prov"], institution_name=institution,
                          status="active", access_token_enc=encrypt_secret(token), external_item_id=claims["inst"])
    db.add(conn)
    db.commit()
    try:
        result = bank_sync.sync_connection(db, conn)          # first sync: accounts + history
    except ProviderError as exc:
        raise HTTPException(502, detail={"message": f"Connected, but the first sync failed: {exc}", "retryable": True})
    db.refresh(conn)
    return {"connected": True, "connection": _conn_out(conn), "imported": result["new"]}


@router.post("/bank/connections/{conn_id}/sync")
def sync_now(conn_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    conn = _mine(db, user, conn_id)
    if conn.provider in ("demo", _STATEMENT_PROVIDER):
        raise HTTPException(422, "This source doesn't sync automatically. Upload a newer statement instead.")
    try:
        result = bank_sync.sync_connection(db, conn)
    except ProviderError as exc:
        raise HTTPException(502, detail={"message": f"Couldn't sync right now: {exc}", "retryable": True})
    db.refresh(conn)
    return {"connection": _conn_out(conn), "new": result["new"]}


@router.delete("/bank/connections/{conn_id}", status_code=204)
def disconnect(conn_id: str, delete_transactions: bool = False,
               user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Revoke: forget the access token and stop syncing. Imported transactions are kept unless asked."""
    conn = _mine(db, user, conn_id)
    if delete_transactions:
        acct_ids = [a.id for a in conn.accounts]
        if acct_ids:
            db.execute(delete(Expense).where(Expense.user_id == user.id, Expense.account_id.in_(acct_ids)))
    db.delete(conn)
    db.commit()


# ---- statement upload (real data, no aggregator) -----------------------------
def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:60] or "account"


@router.post("/bank/statements/parse")
async def parse_statement(file: UploadFile = File(...), password: Optional[str] = Form(None),
                          user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Read a statement and PREVIEW what would be imported. Nothing is saved yet."""
    data = await file.read(statements.MAX_BYTES + 1)
    try:
        res = await run_in_threadpool(statements.parse_statement, data, file.filename or "", password)
    except statements.StatementError as exc:
        raise HTTPException(exc.status_code, detail={"message": exc.message, "code": exc.code, "retryable": False})
    ids = [t.external_id for t in res.txns]
    already: set[str] = set()
    for i in range(0, len(ids), 500):
        already |= set(db.scalars(select(Expense.external_id).where(
            Expense.user_id == user.id, Expense.external_id.in_(ids[i:i + 500]))))
    rules = load_user_rules(db, user.id)
    items = []
    for t in res.txns:
        merchant = normalize_merchant(t.description)
        income = t.amount > 0
        category, csrc = ("Income", "rule") if income else categorize(merchant, t.description, rules)
        items.append({
            "external_id": t.external_id, "date": t.date.isoformat(), "description": t.description, "merchant": merchant,
            "amount": abs(t.amount), "kind": "income" if income else "expense", "balance": t.balance,
            "category": category, "category_source": "rule" if csrc == "none" else csrc,
            "duplicate": t.external_id in already, "direction_guessed": t.direction_guessed,
        })
    period = res.period
    return {
        "filename": file.filename, "bank_hint": res.bank_hint, "count": len(items),
        "new_count": sum(not i["duplicate"] for i in items), "duplicate_count": sum(i["duplicate"] for i in items),
        "skipped_rows": res.skipped_rows, "warnings": res.warnings, "closing_balance": res.closing_balance,
        "period": {"from": period[0].isoformat(), "to": period[1].isoformat()} if period else None,
        "transactions": items,
    }


class ImportItem(BaseModel):
    external_id: str = Field(min_length=6, max_length=128)
    date: date
    description: str = Field(max_length=500)
    merchant: str = Field(min_length=1, max_length=200)
    amount: float = Field(gt=0, lt=1_000_000_000)
    kind: Literal["expense", "income"]
    category: str
    edited: bool = False           # the user changed the category in the preview -> learn it

    @field_validator("category")
    @classmethod
    def _cat(cls, v: str) -> str:
        if v not in CATEGORIES and v != "Income":
            raise ValueError("unknown category")
        return v

    @field_validator("date")
    @classmethod
    def _d(cls, v: date) -> date:
        if not (date(2000, 1, 1) <= v <= date.today() + timedelta(days=2)):
            raise ValueError("date out of range")
        return v


class ImportRequest(BaseModel):
    account_label: str = Field(min_length=1, max_length=80)
    bank_name: str = Field(default="", max_length=80)
    closing_balance: Optional[float] = None
    items: list[ImportItem] = Field(max_length=statements.MAX_ROWS)


@router.post("/bank/statements/import", status_code=201)
def import_statement(req: ImportRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    conn = db.scalar(select(BankConnection).where(BankConnection.user_id == user.id, BankConnection.provider == _STATEMENT_PROVIDER))
    if conn is None:
        conn = BankConnection(user_id=user.id, provider=_STATEMENT_PROVIDER, institution_name="Uploaded statements", status="active")
        db.add(conn)
        db.flush()
    ext = _slug(f"{req.bank_name} {req.account_label}")
    acct = db.scalar(select(BankAccount).where(BankAccount.connection_id == conn.id, BankAccount.external_id == ext))
    if acct is None:
        acct = BankAccount(user_id=user.id, connection_id=conn.id, external_id=ext, name=req.account_label.strip(),
                           mask=req.bank_name.strip(), type="savings", currency="INR")
        db.add(acct)
        db.flush()
    have = set()
    ids = [i.external_id for i in req.items]
    for k in range(0, len(ids), 500):
        have |= set(db.scalars(select(Expense.external_id).where(
            Expense.user_id == user.id, Expense.external_id.in_(ids[k:k + 500]))))
    imported = skipped = 0
    for it in req.items:
        if it.external_id in have:
            skipped += 1
            continue
        have.add(it.external_id)
        db.add(Expense(
            user_id=user.id, source="bank", kind=it.kind, merchant=it.merchant.strip(), amount=Decimal(f"{it.amount:.2f}"),
            currency=user.currency, category="Income" if it.kind == "income" else it.category,
            category_source="user" if it.edited else "rule", date=it.date, account_id=acct.id,
            external_id=it.external_id, raw_description=it.description, user_edited=it.edited))
        if it.edited and it.kind == "expense":
            learn_rule(db, user.id, it.merchant, it.category)
        imported += 1
    if req.closing_balance is not None:
        acct.balance, acct.balance_updated_at = Decimal(str(req.closing_balance)), datetime.now(timezone.utc)
    conn.last_synced_at = datetime.now(timezone.utc)
    db.commit()
    return {"imported": imported, "duplicates_skipped": skipped, "account": {"id": acct.id, "name": acct.name}}
