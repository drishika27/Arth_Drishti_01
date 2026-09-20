"""Shared fixtures for the application-layer tests (users, expenses, OCR,
bank, crypto). Each test gets a fresh in-memory database."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient
    from arth_core.db import Base, configure_engine, get_engine
    from arth_core import models  # noqa: F401
    from arth_core.security import login_limiter
    from arth_bodh.backend.main import app

    configure_engine("sqlite://")            # in-memory, single shared connection
    Base.metadata.create_all(get_engine())
    login_limiter._hits.clear()
    with TestClient(app) as c:
        yield c
    Base.metadata.drop_all(get_engine())


def register(client, email="a@example.com", password="correct-horse-1", name="Test"):
    r = client.post("/auth/register", json={"email": email, "password": password, "name": name})
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture()
def auth(client):
    return register(client)


@pytest.fixture()
def auth2(client):
    return register(client, email="b@example.com")
