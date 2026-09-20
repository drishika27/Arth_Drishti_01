"""
Built-in TEST bank. It behaves like a real Account-Aggregator-style provider
(institutions, a consent step, an opaque access token, accounts, incremental
transactions) but the money is synthetic — every screen labels it "test bank".

Transactions are a deterministic function of (token, date), so a later sync
returns exactly the same history plus any new days, which is what lets the
sync logic be tested for idempotence and incremental updates.
"""
from __future__ import annotations

import random
import secrets
from datetime import date, timedelta
from typing import Optional

from .providers import ProviderAccount, ProviderTxn

HISTORY_DAYS = 90
_INSTITUTIONS = [
    {"id": "sandbox-hdfc", "name": "HDFC Bank (test bank)"},
    {"id": "sandbox-sbi", "name": "State Bank of India (test bank)"},
    {"id": "sandbox-icici", "name": "ICICI Bank (test bank)"},
]
_SPEND = [  # narration template, low, high, weight
    ("UPI/SWIGGY/{ref}/Order", 180, 650, 5), ("UPI/ZOMATO/{ref}/Order", 150, 700, 4), ("POS STARBUCKS COFFEE", 250, 480, 2),
    ("BIGBASKET", 900, 2600, 2), ("UPI/BLINKIT/{ref}/Grocery", 250, 900, 3), ("DMART", 700, 3200, 2),
    ("UPI/UBER/{ref}/Trip", 120, 480, 4), ("OLA CABS", 100, 420, 2), ("BPCL PETROL PUMP", 500, 2200, 1),
    ("AMAZON PAY INDIA", 400, 3500, 3), ("FLIPKART", 500, 4000, 2), ("MYNTRA DESIGNS", 700, 3000, 1),
    ("APOLLO PHARMACY", 200, 1400, 1), ("BOOKMYSHOW", 300, 1200, 1), ("ATM WDL", 500, 5000, 1),
]
_MONTHLY = [(3, "NETFLIX.COM", 649), (7, "SPOTIFY INDIA", 119), (9, "BESCOM ELECTRICITY", 1480),
            (15, "AIRTEL BROADBAND", 999), (1, "NEFT/HOUSE RENT/LANDLORD", 22000)]
OPENING = {"sav": 30000.0, "fund": 120000.0}


def _make_token(institution_id: str) -> str:
    start = (date.today() - timedelta(days=HISTORY_DAYS)).isoformat()
    return f"sbx.{secrets.token_hex(8)}.{start}.{institution_id}"


def _parse_token(token: str) -> tuple[str, date, str]:
    parts = token.split(".")
    if len(parts) != 4 or parts[0] != "sbx":
        raise ValueError("bad sandbox token")
    return parts[1], date.fromisoformat(parts[2]), parts[3]


def _day_txns(seed: str, kind: str, d: date) -> list[tuple[str, float]]:
    """(narration, signed amount) for one day of one account — pure function of its inputs."""
    rng = random.Random(f"{seed}|{kind}|{d.isoformat()}")
    out: list[tuple[str, float]] = []
    if kind == "fund":                       # emergency-fund account: just monthly interest
        if d.day == 5:
            out.append(("INT.PD SAVINGS INTEREST", 350.0))
        return out
    if d.day == 1:                           # salary lands in the everyday account that the spending comes out of
        out.append(("NEFT CR-ACME PVT LTD-SALARY", 97000.0))
    for day, narration, amt in _MONTHLY:
        if d.day == day:
            out.append((narration, -float(amt)))
    if rng.random() < 0.6:
        for _ in range(rng.choice([1, 1, 2])):
            tpl, lo, hi, _w = rng.choices(_SPEND, weights=[s[3] for s in _SPEND])[0]
            out.append((tpl.format(ref=rng.randint(10 ** 8, 10 ** 9 - 1)), -float(round(rng.uniform(lo, hi)))))
    return out


class SandboxProvider:
    id = "sandbox"
    name = "Test bank (sandbox)"
    mode = "sandbox"

    def institutions(self) -> list[dict]:
        return list(_INSTITUTIONS)

    def _inst(self, institution_id: str) -> dict:
        inst = next((i for i in _INSTITUTIONS if i["id"] == institution_id), None)
        if inst is None:
            raise ValueError("Unknown institution")
        return inst

    def consent_details(self, institution_id: str) -> dict:
        inst = self._inst(institution_id)
        return {
            "institution": inst["name"],
            "purpose": "Show your balances and transactions in ArthDrishti to track spending and give insights.",
            "data_requested": ["Account details and balances", "Transaction history (last 90 days, then new activity)"],
            "data_not_requested": ["Your banking password, PIN or OTP", "Permission to move money"],
            "duration_days": 90,
            "note": "This is a TEST bank with synthetic data — no real bank is contacted.",
        }

    def grant_access(self, institution_id: str) -> str:
        self._inst(institution_id)
        return _make_token(institution_id)

    def fetch_accounts(self, token: str) -> list[ProviderAccount]:
        seed, start, _ = _parse_token(token)
        out = []
        for kind, name, mask, typ in (("sav", "Savings Account", "•• 4821", "savings"), ("fund", "Emergency Fund", "•• 9034", "deposit")):
            bal = OPENING[kind] + sum(a for d in self._days(start) for _n, a in _day_txns(seed, kind, d))
            out.append(ProviderAccount(f"sbx-{kind}", name, mask, typ, "INR", round(bal, 2)))
        return out

    @staticmethod
    def _days(start: date):
        d = start
        while d <= date.today():
            yield d
            d += timedelta(days=1)

    def fetch_transactions(self, token: str, account_id: str, since: Optional[date]) -> list[ProviderTxn]:
        seed, start, _ = _parse_token(token)
        kind = account_id.replace("sbx-", "")
        if kind not in OPENING:
            return []
        bal = OPENING[kind]
        out: list[ProviderTxn] = []
        for d in self._days(start):
            for i, (narr, amt) in enumerate(_day_txns(seed, kind, d)):
                bal = round(bal + amt, 2)
                if since is None or d >= since:
                    out.append(ProviderTxn(f"sbx-{kind}-{d.isoformat()}-{i}", d, narr, amt, bal))
        return out
