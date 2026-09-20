"""
AI insights computed from the user's REAL transactions.

Every number here is derived from rows in `expenses` for one user; each
finding cites the expense ids it came from. The chat layer may phrase these
facts (Claude, when configured) but is only ever given these facts.
"""
from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Expense, User


def _month_start(d: date) -> date:
    return d.replace(day=1)


def compute_insights(db: Session, user: User, today: date | None = None) -> dict:
    today = today or date.today()
    start = _month_start(today)
    prev_start = _month_start(start - timedelta(days=1))
    rows = db.scalars(select(Expense).where(
        Expense.user_id == user.id, Expense.ignored.is_(False), Expense.kind == "expense",
        Expense.date >= prev_start - timedelta(days=120))).all()
    income = sum(float(e.amount) for e in db.scalars(select(Expense).where(
        Expense.user_id == user.id, Expense.ignored.is_(False), Expense.kind == "income",
        Expense.date >= start)))

    cur = [e for e in rows if e.date >= start]
    prev = [e for e in rows if prev_start <= e.date < start]
    spend, prev_spend = sum(float(e.amount) for e in cur), sum(float(e.amount) for e in prev)

    def by(key, items):
        out: dict[str, float] = defaultdict(float)
        for e in items:
            out[key(e)] += float(e.amount)
        return dict(sorted(out.items(), key=lambda kv: -kv[1]))

    cats, prev_cats = by(lambda e: e.category, cur), by(lambda e: e.category, prev)
    merchants = by(lambda e: e.merchant, cur)

    findings: list[dict] = []

    # Category spikes vs last month (needs a real prior figure to compare).
    for cat, amt in cats.items():
        before = prev_cats.get(cat, 0)
        if before >= 500 and amt > before * 1.5 and amt - before >= 500:
            findings.append({"kind": "category_spike", "severity": "medium", "title": f"{cat} spending is up",
                             "detail": f"{cat}: ₹{amt:,.0f} this month vs ₹{before:,.0f} last month (+{(amt - before) / before * 100:.0f}%).",
                             "expense_ids": [e.id for e in cur if e.category == cat][:10]})

    # Unusual single transactions: far above this merchant's / category's normal.
    history = defaultdict(list)
    for e in rows:
        history[e.merchant.lower()].append(float(e.amount))
    for e in cur:
        peers = [a for a in history[e.merchant.lower()] if a != float(e.amount)] or []
        cat_peers = [float(x.amount) for x in rows if x.category == e.category and x.id != e.id]
        base, why = None, ""
        if len(peers) >= 3 and float(e.amount) > 3 * statistics.median(peers):
            base, why = statistics.median(peers), f"your usual {e.merchant} charge is about ₹{statistics.median(peers):,.0f}"
        elif len(cat_peers) >= 8:
            mu, sd = statistics.mean(cat_peers), statistics.pstdev(cat_peers)
            if sd and float(e.amount) > mu + 3 * sd and float(e.amount) >= 1000:
                base, why = mu, f"typical {e.category} spend is about ₹{mu:,.0f}"
        if base:
            findings.append({"kind": "unusual_transaction", "severity": "high",
                             "title": f"Unusual charge at {e.merchant}",
                             "detail": f"₹{float(e.amount):,.0f} on {e.date} — {why}.", "expense_ids": [e.id]})

    # Possible duplicate charges: same merchant + amount within 2 days.
    seen: dict[tuple, Expense] = {}
    for e in sorted(rows, key=lambda x: x.date):
        k = (e.merchant.lower(), float(e.amount))
        if k in seen and (e.date - seen[k].date).days <= 2 and e.date >= start - timedelta(days=7):
            findings.append({"kind": "possible_duplicate", "severity": "medium",
                             "title": f"Possible duplicate at {e.merchant}",
                             "detail": f"₹{float(e.amount):,.0f} charged on {seen[k].date} and again on {e.date}.",
                             "expense_ids": [seen[k].id, e.id]})
        seen[k] = e

    # Subscriptions: the same merchant + ~same amount in 2+ distinct months.
    subs = []
    grouped = defaultdict(list)
    for e in rows:
        grouped[e.merchant.lower()].append(e)
    for items in grouped.values():
        months = {(e.date.year, e.date.month) for e in items}
        amts = [float(e.amount) for e in items]
        if len(months) >= 2 and max(amts) - min(amts) <= 0.1 * max(amts):
            subs.append({"merchant": items[0].merchant, "amount": round(statistics.mean(amts), 2), "months_seen": len(months)})

    budget = float(user.monthly_budget) if user.monthly_budget is not None else None
    if budget and spend > budget:
        findings.append({"kind": "budget_overrun", "severity": "high", "title": "Over budget",
                         "detail": f"₹{spend:,.0f} spent against a ₹{budget:,.0f} monthly budget.", "expense_ids": []})
    elif budget and spend > 0.8 * budget:
        findings.append({"kind": "budget_warning", "severity": "medium", "title": "Nearing your budget",
                         "detail": f"₹{spend:,.0f} of ₹{budget:,.0f} used ({spend / budget * 100:.0f}%).", "expense_ids": []})

    return {
        "month": start.strftime("%Y-%m"), "spend": round(spend, 2), "previous_month_spend": round(prev_spend, 2),
        "income": round(income, 2), "net_cash_flow": round(income - spend, 2), "budget": budget,
        "top_categories": [{"category": k, "amount": round(v, 2)} for k, v in list(cats.items())[:5]],
        "top_merchants": [{"merchant": k, "amount": round(v, 2)} for k, v in list(merchants.items())[:5]],
        "subscriptions": subs, "findings": findings, "transaction_count": len(cur),
    }


def answer_question(question: str, facts: dict) -> str:
    """Deterministic answer built ONLY from `facts` (used directly, and as the
    fallback when no LLM is configured)."""
    q = question.lower()
    if facts["transaction_count"] == 0 and not facts["income"]:
        return ("I don't have any transactions for this month yet, so there's nothing to analyse. "
                "Add an expense, scan a receipt, or connect a bank and ask again.")
    if any(w in q for w in ("unusual", "suspicious", "strange", "odd", "duplicate", "fraud")):
        fs = [f for f in facts["findings"] if f["kind"] in ("unusual_transaction", "possible_duplicate")]
        return " ".join(f["detail"] for f in fs[:4]) if fs else "I didn't find any unusual or duplicate charges in your recent transactions."
    if any(w in q for w in ("largest", "biggest", "top", "category", "categories")):
        if not facts["top_categories"]:
            return "No spending recorded this month yet."
        t = facts["top_categories"][0]
        rest = ", ".join(f"{c['category']} ₹{c['amount']:,.0f}" for c in facts["top_categories"][1:3])
        return f"Your largest category this month is {t['category']} at ₹{t['amount']:,.0f}" + (f", followed by {rest}." if rest else ".")
    if any(w in q for w in ("cash", "flow", "income", "save", "saving")):
        return (f"This month you've earned ₹{facts['income']:,.0f} and spent ₹{facts['spend']:,.0f}, "
                f"a net of ₹{facts['net_cash_flow']:,.0f}." + ("" if facts["income"] else " No income entries or bank credits are recorded yet."))
    if any(w in q for w in ("more", "why", "increase", "compare", "last month", "trend")):
        if facts["previous_month_spend"]:
            diff = facts["spend"] - facts["previous_month_spend"]
            spikes = [f["detail"] for f in facts["findings"] if f["kind"] == "category_spike"]
            return (f"You've spent ₹{facts['spend']:,.0f} this month vs ₹{facts['previous_month_spend']:,.0f} last month "
                    f"({'up' if diff >= 0 else 'down'} ₹{abs(diff):,.0f}). " + " ".join(spikes[:2])).strip()
        return f"You've spent ₹{facts['spend']:,.0f} this month, and I have no data for last month to compare with."
    if any(w in q for w in ("subscription", "recurring", "netflix", "monthly")):
        s = facts["subscriptions"]
        return "Recurring charges I can see: " + "; ".join(f"{x['merchant']} ≈ ₹{x['amount']:,.0f}" for x in s[:6]) + "." if s else "I don't see any recurring subscriptions yet."
    if "budget" in q:
        b = facts["budget"]
        return f"You've spent ₹{facts['spend']:,.0f}" + (f" of your ₹{b:,.0f} budget." if b else ". You haven't set a monthly budget yet (Settings).")
    merch = ", ".join(f"{m['merchant']} ₹{m['amount']:,.0f}" for m in facts["top_merchants"][:3])
    return (f"This month: ₹{facts['spend']:,.0f} spent across {facts['transaction_count']} transactions"
            + (f", mostly at {merch}." if merch else ".") + " Ask about categories, cash flow, unusual charges, subscriptions or budget.")
