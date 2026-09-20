"""
Automatic expense categorization.

Order of precedence, most trusted first:
  1. The user's own past corrections (MerchantRule) — learned, per user.
  2. A built-in keyword table of well-known Indian/global merchants.
  3. Optionally, an LLM constrained to the fixed category list (only when
     ANTHROPIC_API_KEY is set, and only for what 1–2 couldn't place).
  4. "Other" — never a guess dressed up as a fact.

Every result carries its `source`, so the UI can show *why* a category was
chosen and the user can correct it.
"""
from __future__ import annotations

import re
from typing import Callable, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import config
from .models import MerchantRule

CATEGORIES = [
    "Food", "Travel", "Shopping", "Groceries", "Subscriptions", "Health",
    "Bills", "Entertainment", "Education", "Other",
]

# brand/keyword -> (display name or None to keep the cleaned text, category)
_KEYWORDS: list[tuple[str, Optional[str], str]] = [
    (r"swiggy", "Swiggy", "Food"), (r"zomato", "Zomato", "Food"),
    (r"domino", "Domino's", "Food"), (r"\bkfc\b", "KFC", "Food"),
    (r"mcdonald", "McDonald's", "Food"), (r"starbucks", "Starbucks", "Food"),
    (r"cafe coffee day|\bccd\b", "Cafe Coffee Day", "Food"),
    (r"restaurant|\bcafe\b|bakery|biryani|pizza|burger|dhaba", None, "Food"),
    (r"\buber\b", "Uber", "Travel"), (r"\bola\b|olacabs", "Ola", "Travel"),
    (r"rapido", "Rapido", "Travel"), (r"irctc", "IRCTC", "Travel"),
    (r"makemytrip|goibibo|redbus|indigo|air india|vistara", None, "Travel"),
    (r"\bmetro\b|petrol|fuel|bpcl|iocl|hpcl|indian oil|shell", None, "Travel"),
    (r"amazon pay|amazon", "Amazon", "Shopping"), (r"flipkart", "Flipkart", "Shopping"),
    (r"myntra", "Myntra", "Shopping"), (r"ajio", "Ajio", "Shopping"),
    (r"nykaa", "Nykaa", "Shopping"), (r"meesho", "Meesho", "Shopping"),
    (r"bigbasket", "BigBasket", "Groceries"), (r"blinkit|grofers", "Blinkit", "Groceries"),
    (r"zepto", "Zepto", "Groceries"), (r"dmart|d-mart|avenue supermarts", "DMart", "Groceries"),
    (r"jiomart", "JioMart", "Groceries"), (r"instamart", "Swiggy Instamart", "Groceries"),
    (r"supermarket|kirana|grocery", None, "Groceries"),
    (r"netflix", "Netflix", "Subscriptions"), (r"spotify", "Spotify", "Subscriptions"),
    (r"prime video", "Prime Video", "Subscriptions"), (r"hotstar", "Disney+ Hotstar", "Subscriptions"),
    (r"youtube (premium|music)", "YouTube Premium", "Subscriptions"),
    (r"icloud|apple\.com/bill|apple services", "Apple", "Subscriptions"),
    (r"google (one|storage)", "Google One", "Subscriptions"), (r"adobe", "Adobe", "Subscriptions"),
    (r"apollo|pharmeasy|1mg|netmeds|medplus|pharmacy|hospital|clinic|diagnostic|dental",
     None, "Health"),
    (r"airtel", "Airtel", "Bills"), (r"\bjio\b|reliance jio", "Jio", "Bills"),
    (r"vodafone|\bvi\b", "Vi", "Bills"), (r"bsnl", "BSNL", "Bills"),
    (r"electricity|bescom|tata power|adani electricity|water bill|gas bill|broadband|fibernet|insurance|\blic\b",
     None, "Bills"),
    (r"bookmyshow", "BookMyShow", "Entertainment"), (r"\bpvr\b|inox", None, "Entertainment"),
    (r"steam|playstation|xbox", None, "Entertainment"),
    (r"udemy|coursera|byju|unacademy|tuition|school fee|college", None, "Education"),
]
_COMPILED = [(re.compile(p, re.I), name, cat) for p, name, cat in _KEYWORDS]

# Noise that bank narrations wrap around the merchant name.
_PREFIX_RE = re.compile(r"^(upi|pos|neft|imps|rtgs|ach|ecs|nach|atm|card|purchase|debit|payment to|paid to)\b[\s/\-:*]*", re.I)
_TOKEN_NOISE_RE = re.compile(r"^(?:\d+|[a-z]*\d[a-z\d]*|ref|txn|no|xx+|\*+)$", re.I)


def normalize_merchant(raw: str) -> str:
    """Turn a bank narration ('UPI/SWIGGY/4581923/Dinner') or a receipt
    header into a short display name ('Swiggy')."""
    text = (raw or "").strip()
    for pattern, display, _cat in _COMPILED:
        if display and pattern.search(text):
            return display
    text = _PREFIX_RE.sub("", text)
    parts = re.split(r"[/|,\-]+|\s{2,}", text)
    for part in parts:
        tokens = [t for t in part.split() if not _TOKEN_NOISE_RE.match(t)]
        if tokens:
            return " ".join(tokens)[:60].title()
    return text[:60].title() or "Unknown"


def merchant_key(merchant: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", "", (merchant or "").lower()).strip()


def rule_category(text: str) -> Optional[str]:
    for pattern, _display, cat in _COMPILED:
        if pattern.search(text or ""):
            return cat
    return None


def load_user_rules(db: Session, user_id: str) -> dict[str, str]:
    rows = db.scalars(select(MerchantRule).where(MerchantRule.user_id == user_id)).all()
    return {r.merchant_key: r.category for r in rows}


def categorize(
    merchant: str,
    description: str = "",
    user_rules: Optional[dict[str, str]] = None,
    llm: Optional[Callable[[str, str], Optional[str]]] = None,
) -> tuple[str, str]:
    """Returns (category, source) where source is user_rule | rule | ai | none."""
    key = merchant_key(merchant)
    if user_rules and key in user_rules:
        return user_rules[key], "user_rule"
    cat = rule_category(f"{merchant} {description}")
    if cat:
        return cat, "rule"
    if llm is not None:
        guess = llm(merchant, description)
        if guess in CATEGORIES:
            return guess, "ai"
    return "Other", "none"


def learn_rule(db: Session, user_id: str, merchant: str, category: str) -> None:
    """Remember the user's correction for next time."""
    key = merchant_key(merchant)
    if not key:
        return
    rule = db.scalar(select(MerchantRule).where(
        MerchantRule.user_id == user_id, MerchantRule.merchant_key == key))
    if rule:
        rule.category = category
    else:
        db.add(MerchantRule(user_id=user_id, merchant_key=key, category=category))


def make_llm_categorizer() -> Optional[Callable[[str, str], Optional[str]]]:
    """A categorizer backed by Claude, constrained to CATEGORIES — or None
    when no ANTHROPIC_API_KEY is configured (rule-based only)."""
    import os
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=key)
    except Exception:
        return None
    model = config.anthropic_model()

    def _ask(merchant: str, description: str) -> Optional[str]:
        try:
            resp = client.messages.create(
                model=model, max_tokens=12,
                system="Classify a bank transaction into exactly one of: "
                       + ", ".join(CATEGORIES) + ". Reply with the category name only.",
                messages=[{"role": "user", "content": f"Merchant: {merchant}\nDescription: {description}"}],
            )
            text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text").strip()
            return next((c for c in CATEGORIES if c.lower() == text.lower().strip(". ")), None)
        except Exception:
            return None

    return _ask
