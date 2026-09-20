"""Connect-a-bank flow (consent -> token -> accounts -> automatic sync) against the built-in test bank."""
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import delete, select

from arth_core.bank import sync as bank_sync
from arth_core.db import session_factory
from arth_core.models import BankConnection, Expense
from arth_core.security import decrypt_secret


def _connect(client, auth, institution="sandbox-hdfc"):
    start = client.post("/bank/connect/start", json={"provider": "sandbox", "institution_id": institution}, headers=auth)
    assert start.status_code == 200, start.text
    done = client.post("/bank/connect/complete", json={"consent_id": start.json()["consent_id"], "approve": True}, headers=auth)
    assert done.status_code == 201, done.text
    return start.json(), done.json()


def _bank_rows(client, auth):
    return [e for e in client.get("/expenses?kind=all&limit=500", headers=auth).json()["items"] if e["source"] == "bank"]


def test_consent_screen_states_what_is_shared_and_what_is_not(client, auth):
    assert client.get("/bank/providers", headers=auth).json()["providers"][0]["institutions"]
    c = client.post("/bank/connect/start", json={"provider": "sandbox", "institution_id": "sandbox-sbi"}, headers=auth).json()["consent"]
    assert "State Bank" in c["institution"] and c["duration_days"] == 90 and "TEST bank" in c["note"]
    assert any("password" in x.lower() for x in c["data_not_requested"]) and any("move money" in x for x in c["data_not_requested"])
    assert client.post("/bank/connect/start", json={"provider": "sandbox", "institution_id": "nope"}, headers=auth).status_code == 422
    assert client.post("/bank/connect/start", json={"provider": "unknown", "institution_id": "x"}, headers=auth).status_code == 422


def test_declining_consent_connects_nothing(client, auth):
    start = client.post("/bank/connect/start", json={"provider": "sandbox", "institution_id": "sandbox-hdfc"}, headers=auth).json()
    r = client.post("/bank/connect/complete", json={"consent_id": start["consent_id"], "approve": False}, headers=auth).json()
    assert r["connected"] is False
    assert client.get("/bank/connections", headers=auth).json()["connections"] == [] and _bank_rows(client, auth) == []


def test_connect_imports_accounts_and_categorised_transactions(client, auth):
    _, done = _connect(client, auth)
    assert done["connected"] and done["imported"] > 40 and done["connection"]["data_mode"] == "sandbox"
    accts = client.get("/bank/accounts", headers=auth).json()["accounts"]
    assert len(accts) == 2 and all(a["balance"] is not None and a["data_mode"] == "sandbox" for a in accts)
    assert all(a["balance"] > 0 for a in accts)                                               # realistic: no overdrawn test accounts
    rows = _bank_rows(client, auth)
    assert all(r["raw_description"] and r["account_name"] for r in rows)
    salary = [r for r in rows if r["kind"] == "income" and r["amount"] == 97000.0]
    assert salary and all(r["merchant"] == "Acme Pvt Ltd" for r in salary)                    # employer name, not "Cr"
    food = [r for r in rows if r["merchant"] in ("Swiggy", "Zomato")]
    assert food and all(r["category"] == "Food" and r["category_source"] == "rule" for r in food)
    s = client.get("/expenses/summary", headers=auth).json()
    assert s["bank_accounts"] == 2 and s["available_funds"] > 0 and s["spend"] > 0


def test_access_token_is_stored_encrypted_and_never_returned(client, auth):
    _, done = _connect(client, auth)
    with session_factory()() as db:
        conn = db.scalar(select(BankConnection))
        assert conn.access_token_enc and not conn.access_token_enc.startswith("sbx.")           # ciphertext, not the token
        assert decrypt_secret(conn.access_token_enc).startswith("sbx.")
    assert "token" not in str(client.get("/bank/connections", headers=auth).json()).lower()
    assert "sbx." not in str(done)


def test_sync_is_idempotent_and_picks_up_only_missing_transactions(client, auth):
    _, done = _connect(client, auth)
    conn_id = done["connection"]["id"]
    total = len(_bank_rows(client, auth))
    assert client.post(f"/bank/connections/{conn_id}/sync", headers=auth).json()["new"] == 0   # nothing new -> nothing added
    assert len(_bank_rows(client, auth)) == total

    # Simulate "new days arrived": drop the last 5 days locally and rewind the cursor; sync restores exactly those.
    cutoff = date.today() - timedelta(days=5)
    with session_factory()() as db:
        gone = len(db.scalars(select(Expense.id).where(Expense.date >= cutoff)).all())
        db.execute(delete(Expense).where(Expense.date >= cutoff))
        db.get(BankConnection, conn_id).sync_cursor = (date.today() - timedelta(days=8)).isoformat()
        db.commit()
    assert gone > 0
    r = client.post(f"/bank/connections/{conn_id}/sync", headers=auth).json()
    assert r["new"] == gone and len(_bank_rows(client, auth)) == total


def test_user_corrections_survive_sync_and_deleted_rows_are_not_resurrected(client, auth):
    _, done = _connect(client, auth)
    conn_id = done["connection"]["id"]
    rows = _bank_rows(client, auth)
    edited = next(r for r in rows if r["merchant"] == "Swiggy")
    client.patch(f"/expenses/{edited['id']}", json={"category": "Groceries", "merchant": "Swiggy Instamart"}, headers=auth)
    gone = next(r for r in rows if r["merchant"] == "Zomato")
    assert client.delete(f"/expenses/{gone['id']}", headers=auth).status_code == 204
    with session_factory()() as db:                                    # rewind so the next sync re-fetches everything
        db.get(BankConnection, conn_id).sync_cursor = None
        db.commit()
    assert client.post(f"/bank/connections/{conn_id}/sync", headers=auth).json()["new"] == 0
    after = {r["id"]: r for r in _bank_rows(client, auth)}
    assert after[edited["id"]]["category"] == "Groceries" and after[edited["id"]]["merchant"] == "Swiggy Instamart"
    assert gone["id"] not in after


def test_learned_rule_applies_to_future_synced_transactions(client, auth):
    _, done = _connect(client, auth)
    conn_id = done["connection"]["id"]
    swiggy = next(r for r in _bank_rows(client, auth) if r["merchant"] == "Swiggy")
    client.patch(f"/expenses/{swiggy['id']}", json={"category": "Groceries"}, headers=auth)   # teach: Swiggy -> Groceries
    with session_factory()() as db:
        db.execute(delete(Expense).where(Expense.date >= date.today() - timedelta(days=40)))
        db.get(BankConnection, conn_id).sync_cursor = (date.today() - timedelta(days=45)).isoformat()
        db.commit()
    client.post(f"/bank/connections/{conn_id}/sync", headers=auth)
    resynced = [r for r in _bank_rows(client, auth) if r["merchant"] == "Swiggy" and r["date"] >= (date.today() - timedelta(days=40)).isoformat()]
    assert resynced and all(r["category"] == "Groceries" and r["category_source"] == "user_rule" for r in resynced)


def test_disconnect_keeps_or_removes_transactions(client, auth):
    _, done = _connect(client, auth)
    n = len(_bank_rows(client, auth))
    assert client.delete(f"/bank/connections/{done['connection']['id']}", headers=auth).status_code == 204
    assert client.get("/bank/connections", headers=auth).json()["connections"] == []
    assert client.get("/bank/accounts", headers=auth).json()["accounts"] == []
    assert len(_bank_rows(client, auth)) == n                                           # history kept by default
    _, done2 = _connect(client, auth, "sandbox-icici")
    client.delete(f"/bank/connections/{done2['connection']['id']}?delete_transactions=true", headers=auth)
    assert all(r["account_id"] is None for r in _bank_rows(client, auth))               # the new connection's rows are gone


def test_consent_tokens_and_connections_are_user_scoped(client, auth, auth2):
    start = client.post("/bank/connect/start", json={"provider": "sandbox", "institution_id": "sandbox-hdfc"}, headers=auth).json()
    assert client.post("/bank/connect/complete", json={"consent_id": start["consent_id"]}, headers=auth2).status_code == 422
    assert client.post("/bank/connect/complete", json={"consent_id": "garbage"}, headers=auth).status_code == 422
    _, done = _connect(client, auth)
    cid = done["connection"]["id"]
    assert client.post(f"/bank/connections/{cid}/sync", headers=auth2).status_code == 404
    assert client.delete(f"/bank/connections/{cid}", headers=auth2).status_code == 404
    assert client.get("/bank/connections", headers=auth2).json()["connections"] == [] and _bank_rows(client, auth2) == []
    # a consent token must never work as a login token
    legacy = client.get("/expenses", headers={"Authorization": f"Bearer {start['consent_id']}"})
    assert legacy.status_code == 401


def test_automatic_background_sync_only_touches_due_connections(client, auth):
    _, done = _connect(client, auth)
    cid = done["connection"]["id"]
    assert bank_sync.sync_all_due() == 0                                                 # just synced -> not due
    with session_factory()() as db:
        db.get(BankConnection, cid).last_synced_at = datetime.now(timezone.utc) - timedelta(hours=3)
        db.commit()
    assert bank_sync.sync_all_due() == 1
    with session_factory()() as db:
        last = db.get(BankConnection, cid).last_synced_at
        last = last.replace(tzinfo=timezone.utc) if last.tzinfo is None else last     # SQLite drops the timezone
        assert last > datetime.now(timezone.utc) - timedelta(minutes=5)


def test_provider_failure_is_recorded_and_reported_not_hidden(client, auth, monkeypatch):
    _, done = _connect(client, auth)
    cid = done["connection"]["id"]
    from arth_core.bank.providers import ProviderError
    from arth_core.bank.sandbox import SandboxProvider

    def boom(self, token):
        raise ProviderError("The bank is temporarily unavailable.")
    monkeypatch.setattr(SandboxProvider, "fetch_accounts", boom)
    r = client.post(f"/bank/connections/{cid}/sync", headers=auth)
    assert r.status_code == 502 and r.json()["detail"]["retryable"] is True
    conn = client.get("/bank/connections", headers=auth).json()["connections"][0]
    assert conn["status"] == "error" and "unavailable" in conn["last_error"]
    assert bank_sync.sync_all_due() == 0                                                 # loop swallows the error, keeps running
    monkeypatch.undo()
    assert client.post(f"/bank/connections/{cid}/sync", headers=auth).status_code == 200
    assert client.get("/bank/connections", headers=auth).json()["connections"][0]["status"] == "active"
