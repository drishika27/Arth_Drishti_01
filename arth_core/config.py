"""
Runtime configuration for the shared application layer (database, CORS,
third-party integrations). Everything is read from environment variables at
call time — never hardcoded — so tests and deployments can override it.
See .env.example for the full list.
"""
from __future__ import annotations

import os


def is_production() -> bool:
    return os.environ.get("ARTHDRISHTI_ENV", "development").lower() == "production"


def database_url() -> str:
    """SQLite by default (zero setup for local dev); Postgres in production
    via DATABASE_URL. Render supplies `postgres://` / `postgresql://` URLs,
    which SQLAlchemy needs rewritten to select the psycopg (v3) driver."""
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        return "sqlite:///./arthdrishti.db"
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


def cors_origins() -> list[str]:
    raw = os.environ.get("CORS_ALLOW_ORIGINS", "").strip()
    if raw:
        return [o.strip() for o in raw.split(",") if o.strip()]
    # Wide open only for local development; production must list its origins.
    return [] if is_production() else ["*"]


def anthropic_model() -> str:
    return os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")


def ocr_model() -> str:
    return os.environ.get("OCR_MODEL", anthropic_model())


def bank_sync_interval_seconds() -> int:
    try:
        return int(os.environ.get("BANK_SYNC_INTERVAL_SECONDS", "900"))
    except ValueError:
        return 900


def eth_rpc_url() -> str:
    return os.environ.get("ETH_RPC_URL", "https://rpc.mevblocker.io")
