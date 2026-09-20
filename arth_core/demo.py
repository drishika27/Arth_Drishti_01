"""
Clearly-labelled SAMPLE data so a fresh account isn't empty.

Everything created here is marked so it can be cleared in one click and is
never mixed up with real data:
  - expenses:  external_id starts with "demo-"
  - bank:      BankConnection.provider == "demo"
  - crypto:    WalletLink.chain == "demo"
The crypto figures below are synthetic (deterministic per user) and the API
labels them `data_mode: "demo"` — they are NOT real balances or prices.
"""
from __future__ import annotations

import random
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .categorizer import categorize, normalize_merchant
from .models import BankAccount, BankConnection, Expense, User, WalletLink

DEMO_PREFIX = "demo-"

# (raw bank description / merchant, low, high, weight)
_POOL = [
    ("UPI/SWIGGY/{ref}/Order", 180, 650, 5), ("UPI/ZOMATO/{ref}/Order", 150, 700, 4),
    ("POS STARBUCKS COFFEE", 250, 480, 2), ("Cafe Coffee Day", 200, 540, 2),
    ("BigBasket", 900, 2600, 2), ("Blinkit", 250, 900, 3), ("DMart", 700, 3200, 2),
    ("UPI/UBER/{ref}/Trip", 120, 480, 4), ("Ola", 100, 420, 2), ("BPCL PETROL PUMP", 500, 2200, 1),
    ("IRCTC", 600, 2400, 1), ("Amazon", 400, 3500, 3), ("Flipkart", 500, 4000, 2), ("Myntra", 700, 3000, 1),
    ("Apollo Pharmacy", 200, 1400, 1), ("PharmEasy", 250, 900, 1), ("BookMyShow", 300, 1200, 1),
]
_FIXED_MONTHLY = [  # (day, raw, amount, category override or None)
    (1, "NEFT/HOUSE RENT/LANDLORD", 22000, "Bills"), (3, "Netflix", 649, None), (7, "Spotify", 119, None),
    (12, "Google One", 130, None), (9, "BESCOM ELECTRICITY", 1480, None), (15, "Airtel Broadband", 999, None),
]


def _rng(user: User) -> random.Random:
    return random.Random(int(user.id[:8], 16))


def is_active(db: Session, user: User) -> bool:
    return db.scalar(select(BankConnection.id).where(
        BankConnection.user_id == user.id, BankConnection.provider == "demo")) is not None


def clear_demo(db: Session, user: User) -> None:
    db.execute(delete(Expense).where(Expense.user_id == user.id, Expense.external_id.like(f"{DEMO_PREFIX}%")))
    db.execute(delete(WalletLink).where(WalletLink.user_id == user.id, WalletLink.chain == "demo"))
    for conn in db.scalars(select(BankConnection).where(
            BankConnection.user_id == user.id, BankConnection.provider == "demo")):
        db.delete(conn)          # cascades to its accounts
    db.commit()


def seed_demo(db: Session, user: User) -> bool:
    """Idempotent. Returns False if sample data is already loaded."""
    if is_active(db, user):
        return False
    rng, today, now = _rng(user), date.today(), datetime.now(timezone.utc)

    conn = BankConnection(user_id=user.id, provider="demo", institution_name="Demo Bank (sample data)",
                          status="active", last_synced_at=now)
    db.add(conn)
    db.flush()
    accounts = []
    for ext, name, mask, typ, bal in [("demo-acc-1", "HDFC Savings", "•• 4421", "savings", "84200.00"),
                                      ("demo-acc-2", "ICICI Salary", "•• 1098", "checking", "42800.00"),
                                      ("demo-acc-3", "SBI Fixed Deposit", "•• 7710", "deposit", "150000.00")]:
        a = BankAccount(user_id=user.id, connection_id=conn.id, external_id=ext, name=name, mask=mask,
                        type=typ, currency="INR", balance=Decimal(bal), balance_updated_at=now)
        db.add(a)
        accounts.append(a)
    db.flush()
    spend_accounts, salary_acct = accounts[:2], accounts[1]

    n = 0

    def add(d: date, raw: str, amount: float, source: str, kind: str = "expense", acct=None, cat=None, note=""):
        nonlocal n
        if d > today:
            return
        n += 1
        merchant = normalize_merchant(raw.format(ref=rng.randint(10**8, 10**9)))
        category, csrc = (cat, "rule") if cat else categorize(merchant, raw)
        db.add(Expense(
            user_id=user.id, source=source, kind=kind, merchant=merchant, amount=Decimal(f"{amount:.2f}"),
            currency="INR", category="Income" if kind == "income" else category,
            category_source=csrc if csrc != "none" else "rule", date=d, note=note,
            account_id=acct.id if acct else None, external_id=f"{DEMO_PREFIX}{n}",
            raw_description=raw.format(ref=rng.randint(10**8, 10**9)) if source == "bank" else None,
            receipt_id=None))

    first_this = today.replace(day=1)
    for m in range(3):
        month_start = (first_this - timedelta(days=30 * m)).replace(day=1)
        add(month_start, "SALARY CREDIT ACME PVT LTD", 97000, "bank", kind="income", acct=salary_acct, cat="Income")
        for day, raw, amt, cat in _FIXED_MONTHLY:
            add(month_start.replace(day=day), raw, amt, "bank", acct=rng.choice(spend_accounts), cat=cat)
        last = (month_start + timedelta(days=31)).replace(day=1) - timedelta(days=1)
        d = month_start
        while d <= min(last, today):
            if rng.random() < 0.6:
                for _ in range(rng.choice([1, 1, 2])):
                    raw, lo, hi, _w = rng.choices(_POOL, weights=[p[3] for p in _POOL])[0]
                    roll = rng.random()
                    src = "bank" if roll < 0.7 else ("ocr" if roll < 0.85 else "manual")
                    add(d, raw, round(rng.uniform(lo, hi)), src,
                        acct=rng.choice(spend_accounts) if src == "bank" else None,
                        note="Scanned receipt" if src == "ocr" else ("Cash" if src == "manual" else ""))
            d += timedelta(days=1)

    # A few things for the insights engine to find.
    add(today - timedelta(days=3), "Amazon", 18499, "bank", acct=spend_accounts[0], note="Laptop bag + accessories")
    add(today - timedelta(days=2), "Zomato", 449, "bank", acct=spend_accounts[0])
    add(today - timedelta(days=1), "Zomato", 449, "bank", acct=spend_accounts[0])

    if user.monthly_budget is None:
        user.monthly_budget = Decimal("60000")

    addr = "0x" + "".join(rng.choice("0123456789abcdef") for _ in range(40))
    db.add(WalletLink(user_id=user.id, address=addr, chain="demo", label="Demo wallet", verified=False))
    db.commit()
    return True


# ---- synthetic crypto overview (labelled demo; never presented as real) ----
def crypto_demo(db: Session, user: User) -> dict | None:
    link = db.scalar(select(WalletLink).where(WalletLink.user_id == user.id, WalletLink.chain == "demo"))
    if link is None:
        return None
    rng = _rng(user)
    holdings = [("ETH", "Ethereum", 1.82, 291450), ("WBTC", "Wrapped Bitcoin", 0.024, 5650000),
                ("LINK", "Chainlink", 140, 1250), ("USDC", "USD Coin", 820, 83.5), ("USDT", "Tether", 510, 83.6)]
    assets = []
    for sym, name, amt, price in holdings:
        ch = round(rng.uniform(-0.3, 0.3) if sym in ("USDC", "USDT") else rng.uniform(-3.5, 5.5), 2)
        assets.append({"symbol": sym, "name": name, "amount": amt, "price_inr": price,
                       "value_inr": round(amt * price, 2), "change_24h_pct": ch})
    total = round(sum(a["value_inr"] for a in assets), 2)
    for a in assets:
        a["allocation_pct"] = round(a["value_inr"] / total * 100, 1)
    day_change = round(sum(a["value_inr"] * a["change_24h_pct"] for a in assets) / total, 2)

    series, v = [], total * 0.86
    for i in range(30):
        v *= 1 + rng.uniform(-0.02, 0.028)
        series.append(v)
    scale = total / series[-1]
    perf = [{"day": (date.today() - timedelta(days=29 - i)).isoformat(), "value_inr": round(x * scale, 2)}
            for i, x in enumerate(series)]

    def short(h): return h[:6] + "…" + h[-4:]
    me = link.address
    txs = []
    for i, (typ, sym, amt) in enumerate([("Received", "ETH", 0.34), ("Sent", "USDC", 240), ("Received", "USDT", 500),
                                         ("Sent", "ETH", 0.08), ("Received", "LINK", 25), ("Sent", "USDC", 120),
                                         ("Received", "WBTC", 0.004), ("Sent", "USDT", 90)]):
        h = "0x" + "".join(rng.choice("0123456789abcdef") for _ in range(64))
        other = "0x" + "".join(rng.choice("0123456789abcdef") for _ in range(40))
        price = next(a["price_inr"] for a in assets if a["symbol"] == sym)
        txs.append({"hash": short(h), "type": typ, "asset": sym, "amount": amt, "value_inr": round(amt * price, 2),
                    "from": short(other if typ == "Received" else me), "to": short(me if typ == "Received" else other),
                    "network": "Ethereum", "status": "Pending" if i == 3 else "Confirmed",
                    "gas_inr": rng.randint(300, 900), "date": (date.today() - timedelta(days=i * 3 + 1)).isoformat()})
    return {
        "data_mode": "demo", "connected": True,
        "disclaimer": "Sample data — synthetic balances and prices for demonstration only.",
        "wallet": {"address": me, "network": "Ethereum Mainnet", "watch_only": True, "verified": False},
        "total_value_inr": total, "change_24h_pct": day_change, "assets": assets,
        "transactions": txs, "performance_30d": perf,
        "security": {
            "risk_label": "Low", "approvals": 3, "address_checks": "8 / 8",
            "checks": [{"ok": True, "title": "Network matches", "detail": "Ethereum Mainnet"},
                       {"ok": True, "title": "Recipient format", "detail": "Valid EVM address"},
                       {"ok": True, "title": "Known scam database", "detail": "No match in sample set"},
                       {"ok": False, "title": "Transaction confirmation", "detail": "Review amount and recipient before signing"}],
        },
    }
