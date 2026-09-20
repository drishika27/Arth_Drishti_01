"""Sample data: clearly labelled, per-user, idempotent, fully removable —
and it feeds the same expense/insight system as real data."""


def test_seed_populates_everything_and_is_labelled(client, auth):
    assert client.get("/demo/status", headers=auth).json()["active"] is False
    assert client.get("/crypto/overview", headers=auth).json() == {"connected": False}

    assert client.post("/demo/seed", headers=auth).json()["loaded"] is True
    assert client.post("/demo/seed", headers=auth).json()["loaded"] is False          # idempotent

    exp = client.get("/expenses?limit=500", headers=auth).json()
    assert exp["total"] > 40
    assert {"bank", "ocr", "manual"} <= {e["source"] for e in exp["items"]}            # all three sources feed one system
    assert all(e["category"] != "" for e in exp["items"])

    s = client.get("/expenses/summary", headers=auth).json()
    assert s["spend"] > 0 and s["income"] > 0 and s["available_funds"] > 0 and s["bank_accounts"] == 3

    banks = client.get("/bank/accounts", headers=auth).json()
    assert len(banks["accounts"]) == 3 and all(a["data_mode"] == "demo" for a in banks["accounts"])

    c = client.get("/crypto/overview", headers=auth).json()
    assert c["data_mode"] == "demo" and "Sample data" in c["disclaimer"]
    assert abs(sum(a["allocation_pct"] for a in c["assets"]) - 100) < 0.5
    assert len(c["performance_30d"]) == 30 and c["transactions"]

    ins = client.get("/insights", headers=auth).json()
    kinds = {f["kind"] for f in ins["findings"]}
    assert "unusual_transaction" in kinds and "possible_duplicate" in kinds and ins["subscriptions"]


def test_clear_removes_only_sample_data(client, auth):
    client.post("/expenses", json={"merchant": "My Real Shop", "amount": 100, "date": "2026-01-05"}, headers=auth)
    client.post("/demo/seed", headers=auth)
    assert client.delete("/demo", headers=auth).json()["active"] is False
    items = client.get("/expenses?limit=500", headers=auth).json()["items"]
    assert [e["merchant"] for e in items] == ["My Real Shop"]
    assert client.get("/bank/accounts", headers=auth).json()["accounts"] == []
    assert client.get("/crypto/overview", headers=auth).json() == {"connected": False}


def test_sample_data_is_per_user(client, auth, auth2):
    client.post("/demo/seed", headers=auth)
    assert client.get("/expenses", headers=auth2).json()["total"] == 0
    assert client.get("/bank/accounts", headers=auth2).json()["accounts"] == []
    assert client.get("/crypto/overview", headers=auth2).json() == {"connected": False}
