"""
Bank sync: pull accounts + new transactions from a provider into the ONE expense
table (source="bank"), auto-categorised, de-duplicated, and safe to run repeatedly.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import config
from ..categorizer import categorize, load_user_rules, make_llm_categorizer, normalize_merchant
from ..db import session_factory
from ..models import BankAccount, BankConnection, Expense
from ..security import decrypt_secret
from .providers import ProviderError, get_provider

log = logging.getLogger("arthdrishti.bank")
OVERLAP_DAYS = 3          # re-fetch a few days so late-posting transactions aren't missed; de-dup makes it safe
MAX_LLM_CALLS = 20


def sync_connection(db: Session, conn: BankConnection) -> dict:
    """Returns {"new": n, "accounts": n}. Raises ProviderError on provider failure (also recorded on the connection)."""
    try:
        provider = get_provider(conn.provider)
        token = decrypt_secret(conn.access_token_enc or "")
        provider_accounts = provider.fetch_accounts(token)
    except (ProviderError, ValueError) as exc:
        conn.status, conn.last_error = "error", str(exc)[:500]
        db.commit()
        raise ProviderError(str(exc)) from exc

    now = datetime.now(timezone.utc)
    existing = {a.external_id: a for a in conn.accounts}
    for pa in provider_accounts:
        acct = existing.get(pa.external_id)
        if acct is None:
            acct = BankAccount(user_id=conn.user_id, connection_id=conn.id, external_id=pa.external_id,
                               name=pa.name, mask=pa.mask, type=pa.type, currency=pa.currency)
            db.add(acct)
            existing[pa.external_id] = acct
        acct.balance = Decimal(str(pa.balance)) if pa.balance is not None else None
        acct.balance_updated_at = now
    db.flush()

    since = (date.fromisoformat(conn.sync_cursor) - timedelta(days=OVERLAP_DAYS)) if conn.sync_cursor else None
    rules = load_user_rules(db, conn.user_id)
    llm, llm_left = make_llm_categorizer(), MAX_LLM_CALLS

    def limited_llm(merchant: str, desc: str):
        nonlocal llm_left
        if llm is None or llm_left <= 0:
            return None
        llm_left -= 1
        return llm(merchant, desc)

    new = 0
    try:
        for pa in provider_accounts:
            acct = existing[pa.external_id]
            txns = provider.fetch_transactions(token, pa.external_id, since)
            have = set(db.scalars(select(Expense.external_id).where(
                Expense.user_id == conn.user_id, Expense.account_id == acct.id,
                Expense.external_id.in_([t.external_id for t in txns] or [""]))))
            for t in txns:
                if t.external_id in have:
                    continue
                income = t.amount > 0
                merchant = normalize_merchant(t.description)
                if income:
                    category, csrc = "Income", "rule"
                else:
                    category, csrc = categorize(merchant, t.description, rules, limited_llm)
                    csrc = "rule" if csrc == "none" else csrc
                db.add(Expense(
                    user_id=conn.user_id, source="bank", kind="income" if income else "expense", merchant=merchant,
                    amount=Decimal(f"{abs(t.amount):.2f}"), currency=pa.currency, category=category, category_source=csrc,
                    date=t.date, account_id=acct.id, external_id=t.external_id, raw_description=t.description[:500]))
                new += 1
    except ProviderError as exc:
        conn.status, conn.last_error = "error", str(exc)[:500]
        db.commit()
        raise
    conn.sync_cursor = date.today().isoformat()
    conn.last_synced_at, conn.status, conn.last_error = now, "active", None
    db.commit()
    return {"new": new, "accounts": len(provider_accounts)}


def sync_all_due() -> int:
    """Sync every active connection that hasn't synced within the interval. Never raises."""
    interval = config.bank_sync_interval_seconds()
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=max(interval, 60))
    done = 0
    with session_factory()() as db:
        conns = db.scalars(select(BankConnection).where(
            BankConnection.status.in_(["active", "error"]), BankConnection.provider != "demo",
            BankConnection.provider != "statement")).all()
        for conn in conns:
            last = conn.last_synced_at
            if last is not None and last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            if last is not None and last > cutoff:
                continue
            try:
                sync_connection(db, conn)
                done += 1
            except Exception as exc:                      # one bad connection must not stop the rest
                log.warning("sync failed for connection %s: %s", conn.id, exc)
                db.rollback()
    return done


async def sync_loop() -> None:
    """Background task: automatic transaction sync every BANK_SYNC_INTERVAL_SECONDS (0 disables)."""
    interval = config.bank_sync_interval_seconds()
    if interval <= 0:
        return
    while True:
        await asyncio.sleep(interval)
        try:
            await asyncio.get_running_loop().run_in_executor(None, sync_all_due)
        except Exception as exc:
            log.warning("bank sync loop error: %s", exc)
