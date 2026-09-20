"""Arth AI: understands real questions (period + category/merchant + intent) and answers from the
user's own data. A fixed 'today' and hand-checkable numbers make every assertion exact."""
from datetime import date
from decimal import Decimal

import pytest

from arth_core import assistant
from arth_core.db import session_factory
from arth_core.models import BankAccount, BankConnection, Expense, User

TODAY = date(2026, 6, 20)


def _add(db, uid, merchant, category, amount, d, kind="expense"):
    db.add(Expense(user_id=uid, source="manual", kind=kind, merchant=merchant, amount=Decimal(str(amount)),
                   category="Income" if kind == "income" else category, date=d, currency="INR"))


@pytest.fixture()
def world(client):
    """June (this month) and May (last month) for one user, plus a second user with different data."""
    r = client.post("/auth/register", json={"email": "ai@example.com", "password": "correct-horse-1", "name": "Asha Rao"}).json()
    uid = r["user"]["id"]
    with session_factory()() as db:
        for m, c, a, d in [("Swiggy", "Food", 400, date(2026, 6, 18)), ("Zomato", "Food", 300, date(2026, 6, 5)),
                           ("Swiggy", "Food", 250, TODAY), ("Uber", "Travel", 150, date(2026, 6, 19)),
                           ("Amazon", "Shopping", 2000, date(2026, 6, 10)), ("Netflix", "Subscriptions", 649, date(2026, 6, 3)),
                           ("House Rent", "Bills", 22000, date(2026, 6, 1)),
                           ("Swiggy", "Food", 500, date(2026, 5, 12)), ("Uber", "Travel", 300, date(2026, 5, 20)),
                           ("Amazon", "Shopping", 800, date(2026, 5, 15)), ("Netflix", "Subscriptions", 649, date(2026, 5, 3)),
                           ("House Rent", "Bills", 22000, date(2026, 5, 1))]:
            _add(db, uid, m, c, a, d)
        _add(db, uid, "Acme Pvt Ltd", "Income", 97000, date(2026, 6, 1), "income")
        _add(db, uid, "Acme Pvt Ltd", "Income", 97000, date(2026, 5, 1), "income")
        db.commit()
    return uid


def ask(uid, question, ctx=None):
    with session_factory()() as db:
        return assistant.respond(db, db.get(User, uid), question, ctx, today=TODAY)


def test_spend_on_a_category_for_this_and_last_month(world):
    a = ask(world, "how much did I spend on food?")["answer"]
    assert "₹950" in a and "3 transactions" in a and "this month" in a and "4%" in a          # 950 of 25,749 total
    last = ask(world, "food spending last month")["answer"]
    assert "₹500" in last and "last month" in last


def test_spend_at_a_merchant_and_totals_and_other_periods(world):
    assert "₹650" in ask(world, "what did I spend at swiggy")["answer"]                        # 400 + 250
    assert "₹250" in ask(world, "how much did I spend today")["answer"]
    assert "₹25,749" in ask(world, "total spending this month")["answer"]
    assert "₹24,249" in ask(world, "how much did I spend in may")["answer"]
    assert "₹22,000" in ask(world, "how much did I pay for rent")["answer"]


def test_top_merchants_categories_and_lists(world):
    m = ask(world, "which merchant do I spend the most at")["answer"]
    assert m.index("House Rent") < m.index("Amazon") and "₹22,000" in m
    c = ask(world, "what is my largest category")["answer"]
    assert "Bills" in c.split(".")[0] and "₹22,000" in c
    lst = ask(world, "show my last 3 transactions")["answer"]
    assert lst.count("•") == 3 and "Swiggy" in lst.splitlines()[1] and "₹250" in lst.splitlines()[1]


def test_compare_trend_cashflow_income(world):
    cmp_ = ask(world, "compare food and travel")["answer"]
    assert "Food: ₹950" in cmp_ and "Travel: ₹150" in cmp_ and "Food is higher" in cmp_
    trend = ask(world, "why did I spend more this month?")["answer"]
    assert "₹1,500" in trend and "up" in trend                                                  # 25,749 vs 24,249
    assert "₹97,000" in ask(world, "how much income did I get")["answer"]
    cf = ask(world, "summarize my cash flow")["answer"]
    assert "₹97,000" in cf and "₹25,749" in cf and "₹71,251" in cf


def test_follow_up_questions_reuse_the_previous_topic(world):
    first = ask(world, "how much did I spend on food?")
    assert first["context"]["category"] == "Food"
    follow = ask(world, "and last month?", first["context"])["answer"]
    assert "₹500" in follow and "last month" in follow                                          # still Food, new period
    other = ask(world, "what about travel?", first["context"])["answer"]
    assert "₹150" in other and "travel" in other.lower()


def test_the_word_and_inside_a_question_is_not_mistaken_for_a_follow_up(world):
    today_q = ask(world, "how much did I spend today")
    cmp_ = ask(world, "compare food and travel", today_q["context"])["answer"]              # would wrongly reuse "today" before
    assert "For this month" in cmp_ and "Food: ₹950" in cmp_ and "Travel: ₹150" in cmp_


def test_answers_read_naturally(world):
    for q in ("how much did I spend on food", "how much did I spend today", "how much did I spend last month", "total spending overall"):
        a = ask(world, q)["answer"]
        assert " in this month" not in a and " in today" not in a and " in last month" not in a and " in all time" not in a
    assert "in May 2026" in ask(world, "how much did I spend in may")["answer"]


def test_saving_tips_ignore_rent_but_include_real_subscriptions(world):
    tips = ask(world, "how can I save money")["answer"]
    assert "Subscriptions: 1 recurring charge (~₹649/month)" in tips and "22,000/month" not in tips


def test_hindi_and_hinglish_keywords(world):
    assert "Bills" in ask(world, "मेरा सबसे बड़ा खर्च क्या है")["answer"]
    assert "₹250" in ask(world, "आज कितना खर्च हुआ")["answer"]
    assert "₹650" in ask(world, "swiggy pe kitna kharcha hua")["answer"]


def test_budget_savings_greeting_and_unknown(world):
    with session_factory()() as db:
        u = db.get(User, world)
        assert "haven't set a monthly budget" in assistant.respond(db, u, "am I over budget", today=TODAY)["answer"]
        u.monthly_budget = Decimal("20000")
        db.commit()
        b = assistant.respond(db, u, "am I over budget?", today=TODAY)["answer"]
    assert "₹25,749" in b and "₹20,000" in b and "over budget" in b
    save = ask(world, "how can I save money")["answer"]
    assert "Shopping" in save and "not financial advice" in save
    greet = ask(world, "hi")["answer"]
    assert greet.startswith("Hi Asha") and "Try asking" in greet
    unk = ask(world, "asdf qwerty zxcv")["answer"]
    assert "not sure I understood" in unk and "•" in unk


def test_balances_and_crypto_use_real_accounts_and_wallets(world, client):
    assert "No bank accounts" in ask(world, "what is my bank balance")["answer"]
    assert "haven't connected a crypto wallet" in ask(world, "how is my crypto doing")["answer"]
    with session_factory()() as db:
        conn = BankConnection(user_id=world, provider="statement", institution_name="Uploaded statements", status="active")
        db.add(conn)
        db.flush()
        db.add(BankAccount(user_id=world, connection_id=conn.id, external_id="a", name="HDFC Savings", balance=Decimal("125000.00")))
        db.commit()
    bal = ask(world, "how much money do I have")["answer"]
    assert "₹1,25,000" in bal and "HDFC Savings" in bal                                         # Indian digit grouping
    token = client.post("/auth/login", json={"email": "ai@example.com", "password": "correct-horse-1"}).json()["access_token"]
    client.post("/demo/seed", headers={"Authorization": f"Bearer {token}"})
    cr = ask(world, "what is my crypto portfolio worth")["answer"]
    assert "sample wallet" in cr and "₹" in cr and "ETH" in cr


def test_other_users_data_never_leaks_into_answers(world, client):
    other = client.post("/auth/register", json={"email": "b@example.com", "password": "correct-horse-1"}).json()["user"]["id"]
    assert "don't have any transactions" in ask(other, "how much did I spend on food?")["answer"]
    with session_factory()() as db:
        _add(db, other, "Chai Point", "Food", 99, TODAY)
        db.commit()
    assert "₹99" in ask(other, "how much did I spend on food?")["answer"] and "₹950" not in ask(other, "food spending")["answer"]


def test_context_from_the_client_is_validated(world):
    for bad in ({"period": ["x", "y"]}, {"intent": "drop table"}, {"category": "Nope", "merchant": 5}, "junk", {"period": [1, 2, 3]}):
        assert ask(world, "and last month?", bad)["answer"]                                     # never crashes


def test_chat_endpoint_round_trips_context_and_indian_formatting(client):
    tok = client.post("/auth/register", json={"email": "c@example.com", "password": "correct-horse-1"}).json()["access_token"]
    h = {"Authorization": f"Bearer {tok}"}
    client.post("/expenses", json={"merchant": "Swiggy", "amount": 125000, "date": date.today().isoformat()}, headers=h)
    r1 = client.post("/ai/chat", json={"question": "how much did I spend on food this month"}, headers=h).json()
    assert "₹1,25,000" in r1["answer"] and r1["engine"] == "rules" and r1["context"]["category"] == "Food"
    r2 = client.post("/ai/chat", json={"question": "and last month?", "context": r1["context"]}, headers=h).json()
    assert "last month" in r2["answer"]
