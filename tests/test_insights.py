"""AI insights + chat are computed from the signed-in user's real data only."""
from datetime import date, timedelta

from tests.conftest import register


def _add(client, auth, merchant, amount, days_ago=0, **kw):
    d = (date.today() - timedelta(days=days_ago)).isoformat()
    r = client.post("/expenses", json={"merchant": merchant, "amount": amount, "date": d, **kw}, headers=auth)
    assert r.status_code == 201, r.text
    return r.json()


def test_chat_with_no_data_is_honest(client, auth):
    a = client.post("/ai/chat", json={"question": "What is my largest category?"}, headers=auth).json()["answer"]
    assert "don't have any transactions" in a


def test_chat_answers_from_real_numbers(client, auth):
    _add(client, auth, "Swiggy", 400)
    _add(client, auth, "Uber", 100)
    _add(client, auth, "Salary", 9000, kind="income")
    top = client.post("/ai/chat", json={"question": "what is my largest category"}, headers=auth).json()["answer"]
    assert "Food" in top and "400" in top
    flow = client.post("/ai/chat", json={"question": "summarize my cash flow"}, headers=auth).json()["answer"]
    assert "9,000" in flow and "500" in flow and "8,500" in flow


def test_unusual_transaction_detected(client, auth):
    for i in range(4):
        _add(client, auth, "Cafe Nero", 200, days_ago=i + 1)
    big = _add(client, auth, "Cafe Nero", 5000)
    ins = client.get("/insights", headers=auth).json()
    unusual = [f for f in ins["findings"] if f["kind"] == "unusual_transaction"]
    assert unusual and big["id"] in unusual[0]["expense_ids"]
    answer = client.post("/ai/chat", json={"question": "any unusual transactions?"}, headers=auth).json()["answer"]
    assert "5,000" in answer


def test_duplicate_charge_and_budget_findings(client, auth):
    _add(client, auth, "Zomato", 350, days_ago=1)
    _add(client, auth, "Zomato", 350, days_ago=0)
    client.patch("/me", json={"monthly_budget": 500}, headers=auth)
    kinds = {f["kind"] for f in client.get("/insights", headers=auth).json()["findings"]}
    assert "possible_duplicate" in kinds and "budget_overrun" in kinds


def test_insights_never_include_other_users_data(client, auth, auth2):
    _add(client, auth, "Swiggy", 999)
    other = client.get("/insights", headers=auth2).json()
    assert other["spend"] == 0 and other["top_merchants"] == []
    assert "don't have any transactions" in client.post("/ai/chat", json={"question": "spend?"}, headers=auth2).json()["answer"]
