"""
Arth AI question answering — grounded in the signed-in user's OWN data.

A small query engine: it works out (intent, period, category/merchant) from the question, then
computes the answer from the user's saved transactions, bank accounts and crypto wallet. Every
number comes from a database query or the wallet reader — nothing is guessed. When Claude is
configured it may re-word the answer, but it is only ever given these computed facts.

It understands English and common Hindi/Hinglish keywords, and keeps light context so a
follow-up like "and last month?" reuses the previous question's topic.
"""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, timedelta
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from .categorizer import CATEGORIES
from .insights import compute_insights
from .models import BankAccount, BankConnection, Expense, User, WalletLink

_CATEGORY_WORDS = {
    "Food": r"food|eating|restaurants?|dining|meals?|zomato|swiggy|snacks?|coffee|khana",
    "Groceries": r"groceries|grocery|kirana|vegetables|sabzi",
    "Travel": r"travel|transport|commute|cabs?|taxis?|fuel|petrol|flights?|trains?|uber|ola",
    "Shopping": r"shopping|clothes|clothing|amazon|flipkart|myntra",
    "Subscriptions": r"subscriptions?|netflix|spotify|ott",
    "Health": r"health|medical|medicine|pharmacy|doctor|hospital",
    "Bills": r"bills?|electricity|rent|internet|broadband|recharge|utilities",
    "Entertainment": r"entertainment|movies?|cinema|gaming|games",
    "Education": r"education|courses?|tuition|school|college",
}
_HINDI = {  # Hindi/Hinglish keyword -> English token the intent rules understand
    "खर्च": "spend", "खर्चा": "spend", "खर्चे": "spend", "कितना": "how much", "सबसे बड़ा": "largest", "सबसे ज्यादा": "largest",
    "कमाई": "income", "आय": "income", "सैलरी": "salary", "बजट": "budget", "बचत": "save", "बैलेंस": "balance", "शेष": "balance",
    "क्रिप्टो": "crypto", "वॉलेट": "wallet", "सब्सक्रिप्शन": "subscriptions", "आज": "today", "कल": "yesterday",
    "इस महीने": "this month", "पिछले महीने": "last month", "इस हफ्ते": "this week", "पिछले हफ्ते": "last week",
    "खाना": "food", "यात्रा": "travel", "खरीदारी": "shopping", "नमस्ते": "hello", "kharcha": "spend", "kitna": "how much",
    "bachat": "save", "paisa": "money",
}
_MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"]


def inr(x: float) -> str:
    """₹ with Indian digit grouping (₹1,24,999)."""
    neg, x = x < 0, abs(round(x))
    s = str(int(x))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        head = re.sub(r"(?<=\d)(?=(\d\d)+$)", ",", head)
        s = f"{head},{tail}"
    return f"{'-' if neg else ''}₹{s}"


# ------------------------------------------------------------------ parsing --
def _normalize(q: str) -> str:
    q = q.lower().strip()
    for k in sorted(_HINDI, key=len, reverse=True):
        q = q.replace(k, f" {_HINDI[k]} ")
    return re.sub(r"\s+", " ", q)


def _when(label: str) -> str:
    """Natural phrasing for a period label: 'today', 'this month', 'overall', 'in June 2026'."""
    if label == "all time":
        return "overall"
    return label if re.match(r"^(today|yesterday|this |last )", label) else f"in {label}"


def _month_range(y: int, m: int) -> tuple[date, date]:
    first = date(y, m, 1)
    nxt = date(y + (m == 12), (m % 12) + 1, 1)
    return first, nxt - timedelta(days=1)


def parse_period(q: str, today: date) -> tuple[date, date, str, bool]:
    """-> (start, end, label, explicit). Defaults to the current month."""
    if re.search(r"\btoday\b", q):
        return today, today, "today", True
    if re.search(r"\byesterday\b", q):
        y = today - timedelta(days=1)
        return y, y, "yesterday", True
    if re.search(r"\blast week\b|\bprevious week\b", q):
        mon = today - timedelta(days=today.weekday() + 7)
        return mon, mon + timedelta(days=6), "last week", True
    if re.search(r"\bthis week\b", q):
        return today - timedelta(days=today.weekday()), today, "this week", True
    if re.search(r"\blast month\b|\bprevious month\b|\bprev month\b", q):
        y, m = (today.year - 1, 12) if today.month == 1 else (today.year, today.month - 1)
        s, e = _month_range(y, m)
        return s, e, "last month", True
    m = re.search(r"\b(?:last|past|previous)\s+(\d{1,3})\s+(day|week|month)s?\b", q)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        days = n * {"day": 1, "week": 7, "month": 30}[unit]
        return today - timedelta(days=days - 1), today, f"the last {n} {unit}{'s' if n != 1 else ''}", True
    if re.search(r"\bthis year\b", q):
        return date(today.year, 1, 1), today, "this year", True
    if re.search(r"\ball time\b|\boverall\b|\bever\b|\bso far\b|\bsince (?:the )?beginning\b", q):
        return date(2000, 1, 1), today, "all time", True
    for i, name in enumerate(_MONTHS, 1):
        mm = re.search(rf"\b(?:in |of |for |during )?{name}(?:\s+(\d{{4}}))?\b", q)
        if mm and not (name == "may" and not re.search(r"\b(in|of|for|during) may\b|\bmay \d{4}\b|\bmay\?*$", q)):
            year = int(mm.group(1)) if mm.group(1) else (today.year if i <= today.month else today.year - 1)
            s, e = _month_range(year, i)
            return s, min(e, today), f"{name.title()} {year}", True
    if re.search(r"\bthis month\b", q):
        return today.replace(day=1), today, "this month", True
    return today.replace(day=1), today, "this month", False


def _find_categories(q: str) -> list[str]:
    return [c for c, pat in _CATEGORY_WORDS.items() if re.search(rf"\b(?:{pat})\b", q)]


def _find_merchants(q: str, merchants: list[str]) -> list[str]:
    hits = [m for m in merchants if len(m) >= 3 and re.search(rf"(?<![a-z0-9]){re.escape(m.lower())}(?![a-z0-9])", q)]
    # prefer the longest names and drop ones contained in a longer hit ("Amazon" vs "Amazon Pay")
    hits.sort(key=len, reverse=True)
    return [h for i, h in enumerate(hits) if not any(h.lower() in o.lower() for o in hits[:i])]


def _n_in(q: str, default: int = 5) -> int:
    m = re.search(r"\b(?:last|recent|latest|top|first)\s+(\d{1,2})\b|\b(\d{1,2})\s+(?:transactions?|expenses?|merchants?)", q)
    return min(int(next(g for g in m.groups() if g)), 20) if m else default


_INTENTS = [  # order matters: first match wins
    ("greeting", r"^(hi|hello|hey|hii+|namaste|good (morning|afternoon|evening))\b|\bwhat can you do\b|\bhelp\b|\bwho are you\b"),
    ("crypto", r"\bcrypto|\bwallet\b|\bportfolio\b|\bethereum\b|\beth\b|\bbitcoin\b|\btokens?\b|\bnft\b"),
    ("balance", r"\bbalance\b|how much (money|cash) (do i|i) have|\bmy funds\b|\bbank account|\bnet worth\b|\bavailable funds\b"),
    ("budget", r"\bbudget\b"),
    ("subscriptions", r"\bsubscriptions?\b|\brecurring\b|\bautopay\b|\bmonthly charges?\b"),
    ("unusual", r"\bunusual\b|\bsuspicious\b|\bstrange\b|\bweird\b|\bodd\b|\bduplicate|\bfraud|\banomal|\bunexpected\b|\bdouble charged\b"),
    ("save", r"\bsave\b|\bsaving|\bcut (down|back)\b|\breduce\b|\blower my\b|\btips?\b|\badvice\b|\bwhere can i\b"),
    ("income", r"\bincome\b|\bearn|\bsalary\b|\bcredited\b|\breceived\b|\bmoney in\b"),
    ("cashflow", r"\bcash ?flow\b|\bnet\b|\bleft over\b|\bremaining money\b"),
    ("list", r"\b(list|show|display)\b.*\b(transactions?|expenses?|purchases?|payments?)\b|\b(last|recent|latest)\b.*\b(transactions?|expenses?|purchases?|payments?)\b|\bmy transactions\b"),
    ("compare", r"\bcompare\b|\bvs\.?\b|\bversus\b|\bdifference between\b"),
    ("top_merchants", r"\bmerchant|where do i (spend|shop)|\bmost (often|frequently)\b|\bwhich (shop|store|app)"),
    ("top_category", r"\blargest\b|\bbiggest\b|\bhighest\b|\btop categor|\bbreakdown\b|\bcategor(y|ies)\b|where (does|did) my money go|\bmost (money|expensive)\b"),
    ("trend", r"\bwhy\b.*\b(more|less|higher|lower|increase|spike|jump)|\bincreas|\btrend\b|\bcompared to\b|\bthan last\b|\bgone up\b"),
    ("spend", r"\bspen[dt]\b|\bspending\b|\bexpenses?\b|\bhow much\b|\bcost\b|\btotal\b|\bpaid\b|\bpay\b|\bpurchases?\b"),
]


def detect_intent(q: str) -> Optional[str]:
    for name, pat in _INTENTS:
        if re.search(pat, q):
            return name
    return None


# ----------------------------------------------------------------- data ------
class _Data:
    def __init__(self, db: Session, user: User, today: date):
        self.db, self.user, self.today = db, user, today
        self.rows: list[Expense] = list(db.scalars(select(Expense).where(
            Expense.user_id == user.id, Expense.ignored.is_(False))))
        self.merchants = sorted({r.merchant for r in self.rows if r.kind == "expense"})

    def spend(self, start: date, end: date, category: Optional[str] = None, merchant: Optional[str] = None,
              kind: str = "expense") -> list[Expense]:
        return [r for r in self.rows if r.kind == kind and start <= r.date <= end
                and (category is None or r.category == category)
                and (merchant is None or r.merchant.lower() == merchant.lower())]

    @staticmethod
    def total(rows: list[Expense]) -> float:
        return round(sum(float(r.amount) for r in rows), 2)


def _group(rows: list[Expense], key) -> list[tuple[str, float]]:
    agg: dict[str, float] = defaultdict(float)
    for r in rows:
        agg[key(r)] += float(r.amount)
    return sorted(agg.items(), key=lambda kv: -kv[1])


def _prev_period(start: date, end: date) -> tuple[date, date]:
    span = (end - start).days + 1
    return start - timedelta(days=span), start - timedelta(days=1)


def _crypto_summary(db: Session, user: User) -> Optional[dict]:
    from . import crypto, demo
    links = db.scalars(select(WalletLink).where(WalletLink.user_id == user.id).order_by(WalletLink.created_at)).all()
    live = [w for w in links if w.chain != "demo"]
    w = (live or links or [None])[0]
    if w is None:
        return None
    if w.chain == "demo":
        return demo.crypto_demo(db, user)
    try:
        return crypto.get_overview(w.address, verified_owner=w.verified)
    except crypto.ChainDataError:
        return {"error": True}


# ---------------------------------------------------------------- answers ----
def _examples() -> str:
    return ("• How much did I spend on food last month?\n• What did I spend at Swiggy?\n• Which merchant do I spend the most at?\n"
            "• Show my last 5 transactions\n• Am I over budget?\n• What's my bank balance?\n• How is my crypto doing?\n• How can I save money?")


_KNOWN_INTENTS = {n for n, _ in _INTENTS}


def _safe_ctx(ctx: Any) -> dict:
    """The follow-up context round-trips through the client, so re-validate every field."""
    if not isinstance(ctx, dict):
        return {}
    out: dict = {}
    if ctx.get("intent") in _KNOWN_INTENTS:
        out["intent"] = ctx["intent"]
    try:
        p = ctx.get("period")
        if isinstance(p, list) and len(p) == 2:
            out["period"] = [date.fromisoformat(str(p[0])).isoformat(), date.fromisoformat(str(p[1])).isoformat()]
            out["period_label"] = str(ctx.get("period_label", "that period"))[:40]
    except ValueError:
        out.pop("period", None)
    if ctx.get("category") in CATEGORIES:
        out["category"] = ctx["category"]
    if isinstance(ctx.get("merchant"), str):
        out["merchant"] = ctx["merchant"][:100]
    return out


def respond(db: Session, user: User, question: str, ctx: Optional[dict] = None, today: Optional[date] = None) -> dict:
    today = today or date.today()
    q = _normalize(question)
    d = _Data(db, user, today)
    ctx = _safe_ctx(ctx)

    start, end, label, explicit = parse_period(q, today)
    cats, merchants = _find_categories(q), _find_merchants(q, d.merchants)
    # A follow-up starts with "and…", "what about…", "how about…", "also…" — not just contains "and".
    follow_up = bool(re.match(r"^\s*(and|also|then|what about|how about|same for|what of)\b", q)) and len(q.split()) <= 9
    if ctx.get("period") and not explicit and follow_up:
        start, end, label = date.fromisoformat(ctx["period"][0]), date.fromisoformat(ctx["period"][1]), ctx["period_label"]
    intent = detect_intent(q)
    if intent is None:
        if (cats or merchants or explicit) and ctx.get("intent") and follow_up:
            intent = ctx["intent"]                         # follow-up: "and last month?" / "what about travel?"
        elif cats or merchants:
            intent = "spend"
    if intent in ("spend", "list", "trend") and ctx.get("intent") and not cats and not merchants and follow_up:
        cats = [ctx["category"]] if ctx.get("category") else cats
        merchants = [ctx["merchant"]] if ctx.get("merchant") else merchants

    out_ctx = {"intent": intent, "period": [start.isoformat(), end.isoformat()], "period_label": label,
               "category": cats[0] if cats else None, "merchant": merchants[0] if merchants else None}

    def reply(text: str) -> dict:
        return {"answer": text, "intent": intent or "unknown", "context": out_ctx}

    data_intents = {"spend", "list", "compare", "top_merchants", "top_category", "trend", "cashflow", "income", "save", "unusual", "subscriptions"}
    if intent in data_intents and not d.rows:
        return reply("I don't have any transactions for this month yet, so there's nothing to analyse. "
                     "Add an expense, scan a receipt, import a bank statement or connect a bank, and ask again.")

    if intent == "greeting":
        month = d.total(d.spend(today.replace(day=1), today))
        snap = f" So far this month you've spent {inr(month)}." if d.rows else ""
        return reply(f"Hi {user.name.split()[0] if user.name else 'there'}! I can answer questions about your spending, bank balances and crypto wallet.{snap}\n\nTry asking:\n{_examples()}")

    if intent == "crypto":
        c = _crypto_summary(db, user)
        if c is None:
            return reply("You haven't connected a crypto wallet yet. Open the Wallet page to connect yours or watch any public address, and I'll be able to answer questions about it.")
        if c.get("error"):
            return reply("I couldn't read the blockchain data right now (the data provider is busy). Please try again in a minute.")
        tot, ch = c.get("total_value_inr"), c.get("change_24h_pct")
        priced = sorted((a for a in c["assets"] if a.get("value_inr")), key=lambda a: -a["value_inr"])[:4]
        top = ", ".join(f"{a['symbol']} {inr(a['value_inr'])}" for a in priced)
        parts = [f"Your {'sample ' if c['data_mode'] == 'demo' else ''}wallet holds about {inr(tot)}" + (f" ({'+' if ch >= 0 else ''}{ch}% in 24h)" if ch is not None else "") + "." if tot is not None
                 else "I can see your balances but prices aren't available right now, so I can't total the value."]
        if top:
            parts.append(f"Biggest holdings: {top}.")
        if c.get("transactions"):
            t = c["transactions"][0]
            parts.append(f"Latest activity: {t['type'].lower()} {t['asset']} on {(t.get('date') or '')[:10]}.")
        return reply(" ".join(parts))

    if intent == "balance":
        rows = db.execute(select(BankAccount, BankConnection).join(BankConnection, BankAccount.connection_id == BankConnection.id)
                          .where(BankAccount.user_id == user.id)).all()
        if not rows:
            return reply("No bank accounts are linked yet. Connect a bank or import a statement on the Funds page and I can tell you your balances.")
        known = [(a, c) for a, c in rows if a.balance is not None]
        total = sum(float(a.balance) for a, _ in known)
        lines = "\n".join(f"• {a.name} ({c.institution_name}): {inr(float(a.balance))}" for a, c in known)
        note = " (includes sample/test data)" if any(c.provider in ("demo", "sandbox") for _, c in rows) else ""
        return reply(f"Across {len(known)} account{'s' if len(known) != 1 else ''} you have {inr(total)}{note}:\n{lines}")

    if intent == "budget":
        ins = compute_insights(db, user, today)
        b, s = ins["budget"], ins["spend"]
        if not b:
            return reply(f"You've spent {inr(s)} this month. You haven't set a monthly budget yet — add one in Settings and I'll track it.")
        left = b - s
        left_txt = f"{inr(left)} left" if left >= 0 else f"{inr(-left)} over budget"
        days_left = (_month_range(today.year, today.month)[1] - today).days
        extra = f" That's about {inr(left / days_left)} per day for the remaining {days_left} days." if left > 0 and days_left > 0 else ""
        return reply(f"You've spent {inr(s)} of your {inr(b)} monthly budget ({s / b * 100:.0f}%) — {left_txt}.{extra}")

    if intent == "subscriptions":
        subs = compute_insights(db, user, today)["subscriptions"]
        if not subs:
            return reply("I don't see any recurring subscriptions yet — I need the same charge in at least two different months.")
        total = sum(s["amount"] for s in subs)
        return reply(f"I found {len(subs)} recurring charges costing about {inr(total)} a month:\n" + "\n".join(f"• {s['merchant']} ≈ {inr(s['amount'])}" for s in subs[:8]))

    if intent == "unusual":
        fs = [f for f in compute_insights(db, user, today)["findings"] if f["kind"] in ("unusual_transaction", "possible_duplicate")]
        return reply(" ".join(f["detail"] for f in fs[:4]) if fs else "I didn't find any unusual or duplicate charges in your recent transactions.")

    if intent == "income":
        rows = d.spend(start, end, kind="income")
        if not rows:
            return reply(f"I don't see any income recorded for {label}. Income shows up from bank credits or income entries.")
        src = _group(rows, lambda r: r.merchant)[:3]
        return reply(f"You received {inr(d.total(rows))} {_when(label)}, from " + ", ".join(f"{m} {inr(a)}" for m, a in src) + ".")

    if intent == "cashflow":
        inc, exp = d.total(d.spend(start, end, kind="income")), d.total(d.spend(start, end))
        return reply(f"For {label} you've earned {inr(inc)} and spent {inr(exp)}, a net of {inr(inc - exp)}."
                     + ("" if inc else " No income entries or bank credits are recorded for this period."))

    if intent == "save":
        s0, e0 = today.replace(day=1), today
        cur = d.spend(s0, e0)
        if not cur:
            return reply("I need some spending this month to suggest where to cut back. Add or import a few transactions first.")
        by_cat = _group(cur, lambda r: r.category)
        soft = [(c, a) for c, a in by_cat if c in ("Shopping", "Food", "Entertainment", "Subscriptions")]
        ins = compute_insights(db, user, today)
        tips = []
        for c, a in soft[:2]:
            n = len([r for r in cur if r.category == c])
            tips.append(f"• {c}: {inr(a)} across {n} purchases this month — trimming 20% would save about {inr(a * 0.2)}.")
        sub_merchants = {r.merchant.lower() for r in d.rows if r.kind == "expense" and r.category in ("Subscriptions", "Entertainment")}
        subs = [s for s in ins["subscriptions"] if s["merchant"].lower() in sub_merchants]     # rent/bills aren't cancellable subscriptions
        if subs:
            tips.append(f"• Subscriptions: {len(subs)} recurring charge{'s' if len(subs) != 1 else ''} (~{inr(sum(s['amount'] for s in subs))}/month) — cancel any you don't use.")
        dupes = [f for f in ins["findings"] if f["kind"] == "possible_duplicate"]
        if dupes:
            tips.append(f"• {dupes[0]['detail']} — check if it was charged twice.")
        if ins["budget"] and ins["spend"] > ins["budget"]:
            tips.append(f"• You're {inr(ins['spend'] - ins['budget'])} over your budget, so start with the categories above.")
        return reply("Based on your actual spending this month:\n" + ("\n".join(tips) if tips else f"• Your biggest category is {by_cat[0][0]} at {inr(by_cat[0][1])} — start there.")
                     + "\nThese are suggestions from your own numbers, not financial advice.")

    if intent == "list":
        n = _n_in(q)
        rows = sorted(d.spend(start if explicit else date(2000, 1, 1), end, cats[0] if cats else None, merchants[0] if merchants else None),
                      key=lambda r: (r.date, r.created_at), reverse=True)[:n]
        if not rows:
            return reply("I couldn't find any matching transactions.")
        return reply(f"Your {'latest ' + str(len(rows)) if not explicit else 'transactions for ' + label}:\n"
                     + "\n".join(f"• {r.date} — {r.merchant} ({r.category}): {inr(float(r.amount))}" for r in rows))

    if intent == "top_merchants":
        rows = d.spend(start, end, cats[0] if cats else None)
        if not rows:
            return reply(f"I don't see any spending for {label}.")
        top = _group(rows, lambda r: r.merchant)[:_n_in(q, 5)]
        return reply(f"Where you spent the most {_when(label)}:\n" + "\n".join(f"• {m}: {inr(a)}" for m, a in top))

    if intent == "compare":
        items = [("category", c) for c in cats] + [("merchant", m) for m in merchants]
        if len(items) >= 2:
            lines, vals = [], []
            for kind, name in items[:4]:
                rows = d.spend(start, end, category=name if kind == "category" else None, merchant=name if kind == "merchant" else None)
                vals.append((name, d.total(rows), len(rows)))
                lines.append(f"• {name}: {inr(d.total(rows))} ({len(rows)} transactions)")
            lead = max(vals, key=lambda v: v[1])
            return reply(f"For {label}:\n" + "\n".join(lines) + (f"\n{lead[0]} is higher." if lead[1] > 0 else ""))
        intent = "trend"      # "compare with last month" -> period comparison

    if intent in ("top_category",):
        rows = d.spend(start, end)
        if not rows:
            return reply(f"I don't see any spending for {label}.")
        cat_totals = _group(rows, lambda r: r.category)
        tot = d.total(rows)
        head = f"Your largest category {_when(label)} is {cat_totals[0][0]} at {inr(cat_totals[0][1])}"
        rest = ", ".join(f"{c} {inr(a)}" for c, a in cat_totals[1:3])
        breakdown = "\n".join(f"• {c}: {inr(a)} ({a / tot * 100:.0f}%)" for c, a in cat_totals[:6])
        return reply(head + (f", followed by {rest}." if rest else ".") + f"\n\nFull breakdown ({inr(tot)} total):\n{breakdown}")

    if intent == "trend":
        cur_s, cur_e = start, end
        if not explicit:
            cur_s, cur_e, label = today.replace(day=1), today, "this month"
        ps, pe = _prev_period(cur_s, cur_e) if label != "this month" else _month_range(*((today.year - 1, 12) if today.month == 1 else (today.year, today.month - 1)))
        cur, prev = d.spend(cur_s, cur_e), d.spend(ps, pe)
        if not prev:
            return reply(f"You've spent {inr(d.total(cur))} {_when(label)}, and I have no earlier data to compare with.")
        diff = d.total(cur) - d.total(prev)
        cats_c, cats_p = dict(_group(cur, lambda r: r.category)), dict(_group(prev, lambda r: r.category))
        drivers = sorted(((c, cats_c.get(c, 0) - cats_p.get(c, 0)) for c in set(cats_c) | set(cats_p)), key=lambda kv: -abs(kv[1]))[:3]
        why = "; ".join(f"{c} {'up' if v >= 0 else 'down'} {inr(abs(v))}" for c, v in drivers if abs(v) >= 100)
        return reply(f"You spent {inr(d.total(cur))} {_when(label)} vs {inr(d.total(prev))} before that — {'up' if diff >= 0 else 'down'} {inr(abs(diff))}."
                     + (f" Biggest changes: {why}." if why else ""))

    if intent == "spend":
        cat, mer = (cats[0] if cats else None), (merchants[0] if merchants else None)
        rows = d.spend(start, end, cat, mer)
        what = mer or (cat.lower() if cat else "in total")
        subject = f"on {what}" if cat else (f"at {mer}" if mer else "")
        if not rows:
            return reply(f"I don't see any spending {subject + ' ' if subject else ''}for {label}.".replace("  ", " "))
        tot, n = d.total(rows), len(rows)
        all_tot = d.total(d.spend(start, end))
        msg = f"You spent {inr(tot)} {subject + ' ' if subject else ''}{_when(label)} across {n} transaction{'s' if n != 1 else ''}"
        msg += f" (average {inr(tot / n)})." if n > 1 else "."
        if (cat or mer) and all_tot and tot != all_tot:
            msg += f" That's {tot / all_tot * 100:.0f}% of your {inr(all_tot)} total spending."
        if not (cat or mer):
            top = _group(rows, lambda r: r.category)[:3]
            msg += " Mostly " + ", ".join(f"{c} {inr(a)}" for c, a in top) + "."
        return reply(msg)

    return reply("I'm not sure I understood that. I can answer questions about your own spending, bank balances and crypto wallet, for example:\n" + _examples())


# ----------------------------------------------------------------- LLM facts --
def llm_facts(db: Session, user: User, today: Optional[date] = None) -> dict[str, Any]:
    """A compact, fully computed fact pack — the ONLY thing the language model is allowed to use."""
    today = today or date.today()
    d = _Data(db, user, today)
    months = {}
    for i in range(3):
        y, m = today.year, today.month - i
        while m <= 0:
            y, m = y - 1, m + 12
        s, e = _month_range(y, m)
        rows = d.spend(s, e)
        months[f"{y}-{m:02d}"] = {"spend": d.total(rows), "income": d.total(d.spend(s, e, kind="income")),
                                  "by_category": dict(_group(rows, lambda r: r.category))}
    recent = sorted((r for r in d.rows if r.kind == "expense"), key=lambda r: (r.date, r.created_at), reverse=True)[:15]
    accts = db.scalars(select(BankAccount).where(BankAccount.user_id == user.id)).all()
    crypto = _crypto_summary(db, user)
    return {
        "today": today.isoformat(), "currency": "INR", "months": months, "insights": compute_insights(db, user, today),
        "recent_transactions": [{"date": r.date.isoformat(), "merchant": r.merchant, "category": r.category, "amount": float(r.amount)} for r in recent],
        "bank_accounts": [{"name": a.name, "balance": float(a.balance) if a.balance is not None else None} for a in accts],
        "crypto": None if not crypto or crypto.get("error") else {"total_value_inr": crypto.get("total_value_inr"), "change_24h_pct": crypto.get("change_24h_pct"),
                                                                    "top_assets": [{"symbol": a["symbol"], "value_inr": a.get("value_inr")} for a in crypto["assets"][:5]],
                                                                    "sample_data": crypto["data_mode"] == "demo"},
    }
