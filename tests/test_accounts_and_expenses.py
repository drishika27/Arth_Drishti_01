"""Accounts, authentication, validation and per-user data isolation for the
unified expense system."""
from datetime import date

from arth_core.security import hash_password, verify_password
from tests.conftest import register


def _expense(client, auth, **over):
    body = {"merchant": "Swiggy", "amount": 420, "date": date.today().isoformat(), "note": "Dinner"}
    body.update(over)
    return client.post("/expenses", json=body, headers=auth)


# ---- passwords / auth ------------------------------------------------------
def test_password_hash_roundtrip_and_no_plaintext():
    h = hash_password("s3cret-pass")
    assert "s3cret-pass" not in h
    assert verify_password("s3cret-pass", h)
    assert not verify_password("wrong", h)
    assert not verify_password("x", "garbage")


def test_register_login_refresh_flow(client):
    r = client.post("/auth/register", json={"email": "New@Example.com", "password": "longenough1"})
    assert r.status_code == 201 and r.json()["user"]["email"] == "new@example.com"
    assert client.post("/auth/register", json={"email": "new@example.com", "password": "longenough1"}).status_code == 409

    login = client.post("/auth/login", json={"email": "new@example.com", "password": "longenough1"})
    assert login.status_code == 200
    tokens = login.json()
    me = client.get("/me", headers={"Authorization": f"Bearer {tokens['access_token']}"})
    assert me.status_code == 200 and me.json()["email"] == "new@example.com"

    # A refresh token is not an access token, and vice versa.
    assert client.get("/me", headers={"Authorization": f"Bearer {tokens['refresh_token']}"}).status_code == 401
    assert client.post("/auth/refresh", json={"refresh_token": tokens["access_token"]}).status_code == 401
    ref = client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert ref.status_code == 200 and ref.json()["access_token"]


def test_login_rejects_bad_credentials_and_throttles(client):
    register(client)
    for _ in range(8):
        assert client.post("/auth/login", json={"email": "a@example.com", "password": "nope-nope"}).status_code == 401
    assert client.post("/auth/login", json={"email": "a@example.com", "password": "correct-horse-1"}).status_code == 429


def test_register_validation(client):
    assert client.post("/auth/register", json={"email": "not-an-email", "password": "longenough1"}).status_code == 422
    assert client.post("/auth/register", json={"email": "a@b.co", "password": "short"}).status_code == 422


def test_endpoints_require_a_user_token(client):
    assert client.get("/expenses").status_code in (401, 403)
    assert client.get("/expenses", headers={"Authorization": "Bearer junk"}).status_code == 401
    # The legacy API-key token is not a user identity.
    legacy = client.post("/auth/token", json={"api_key": "dev-local-key-not-for-production"}).json()["access_token"]
    assert client.get("/expenses", headers={"Authorization": f"Bearer {legacy}"}).status_code == 401


# ---- expenses CRUD + validation -------------------------------------------
def test_expense_crud_roundtrip(client, auth):
    r = _expense(client, auth)
    assert r.status_code == 201
    e = r.json()
    assert e["category"] == "Food" and e["source"] == "manual" and e["amount"] == 420.0   # auto-categorized

    listed = client.get("/expenses", headers=auth).json()
    assert listed["total"] == 1 and listed["items"][0]["merchant"] == "Swiggy"

    upd = client.patch(f"/expenses/{e['id']}", json={"amount": 500, "note": "Lunch"}, headers=auth)
    assert upd.status_code == 200 and upd.json()["amount"] == 500 and upd.json()["user_edited"] is True

    assert client.delete(f"/expenses/{e['id']}", headers=auth).status_code == 204
    assert client.get("/expenses", headers=auth).json()["total"] == 0


def test_expense_validation(client, auth):
    assert _expense(client, auth, amount=-5).status_code == 422
    assert _expense(client, auth, amount=0).status_code == 422
    assert _expense(client, auth, merchant="   ").status_code == 422
    assert _expense(client, auth, category="NotACategory").status_code == 422
    assert _expense(client, auth, date="2999-01-01").status_code == 422


def test_data_isolation_between_users(client, auth, auth2):
    mine = _expense(client, auth).json()
    # User B sees nothing of A's data and cannot touch it (404, not 403 — no id oracle).
    assert client.get("/expenses", headers=auth2).json()["total"] == 0
    assert client.patch(f"/expenses/{mine['id']}", json={"amount": 1}, headers=auth2).status_code == 404
    assert client.delete(f"/expenses/{mine['id']}", headers=auth2).status_code == 404
    assert client.get("/expenses", headers=auth).json()["items"][0]["amount"] == 420.0
    assert client.get("/expenses/summary", headers=auth2).json()["spend"] == 0


# ---- categorization + learning --------------------------------------------
def test_user_correction_is_learned_for_future_entries(client, auth):
    first = _expense(client, auth, merchant="Corner Store XYZ").json()
    assert first["category"] == "Other"
    client.patch(f"/expenses/{first['id']}", json={"category": "Groceries"}, headers=auth)
    second = _expense(client, auth, merchant="corner store xyz").json()
    assert second["category"] == "Groceries" and second["category_source"] == "user_rule"


def test_apply_to_similar_recategorizes_uncorrected_rows(client, auth):
    a = _expense(client, auth, merchant="Local Mart").json()
    b = _expense(client, auth, merchant="Local Mart").json()
    r = client.patch(f"/expenses/{a['id']}", json={"category": "Groceries", "apply_to_similar": True}, headers=auth)
    assert r.json()["updated_similar"] == 1
    items = {i["id"]: i for i in client.get("/expenses", headers=auth).json()["items"]}
    assert items[b["id"]]["category"] == "Groceries"


# ---- summary ---------------------------------------------------------------
def test_summary_reflects_real_rows_and_budget(client, auth):
    _expense(client, auth, merchant="Swiggy", amount=400)
    _expense(client, auth, merchant="Uber", amount=100)
    _expense(client, auth, merchant="Salary", amount=5000, kind="income")
    client.patch("/me", json={"monthly_budget": 1000}, headers=auth)
    s = client.get("/expenses/summary", headers=auth).json()
    assert s["spend"] == 500 and s["income"] == 5000
    assert s["budget"] == 1000 and s["remaining_budget"] == 500
    assert {c["category"] for c in s["categories"]} == {"Food", "Travel"}
    assert len(s["last_7_days"]) == 7 and s["available_funds"] is None   # no bank linked -> no invented balance
