"""
Shared JWT + API-key authentication for both backends' endpoints.

Model: a client trades a long-lived API key for a short-lived (1 hour)
JWT via POST /auth/token, then sends `Authorization: Bearer <token>` on
every subsequent request. This is the same pattern used by most real
API platforms (issue a key once, mint short-lived session tokens from
it) rather than either extreme (raw API keys on every call forever, or a
full username/password + refresh-token system this app has no user
database to support).

Uses FastAPI's HTTPBearer security scheme (not a raw Header() dependency)
specifically so /docs (Swagger UI) shows a real "Authorize" button and
marks protected endpoints with a lock icon — auth that isn't documented
in the OpenAPI schema isn't really documented.

Honest default: if ARTHDRISHTI_API_KEYS isn't set, a single well-known
dev key is accepted so the README's own curl examples and the demo
frontends work with zero setup — this is loudly not a production
default (see the warning below), and is exactly the same "runs with
zero config, tell the user plainly when that's a fallback" pattern this
codebase already uses for ANTHROPIC_API_KEY and the default RPC.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Optional

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

logger = logging.getLogger("arthdrishti.auth")

_DEV_FALLBACK_KEY = "dev-local-key-not-for-production"
_ALGORITHM = "HS256"
_TOKEN_TTL_SECONDS = 3600

# A JWT signing secret survives only this process's lifetime unless
# JWT_SECRET is set — fine for a single dev/demo process (tokens it
# issues are only ever verified by that same process), but every real
# deployment must set JWT_SECRET explicitly or tokens won't survive a
# restart and can't be verified across multiple worker processes.
def _is_production() -> bool:
    return os.environ.get("ARTHDRISHTI_ENV", "development").lower() == "production"


_SECRET = os.environ.get("JWT_SECRET")
if not _SECRET:
    if _is_production():
        # A per-process random secret would silently break every login on
        # restart / across workers; refuse to start instead of limping.
        raise RuntimeError("JWT_SECRET must be set when ARTHDRISHTI_ENV=production.")
    import secrets
    _SECRET = secrets.token_hex(32)
    logger.warning(
        "JWT_SECRET not set — using a random secret generated for this process only. "
        "Tokens will stop working on restart and won't work across multiple workers. "
        "Set JWT_SECRET explicitly for any real deployment."
    )


def _valid_api_keys() -> set[str]:
    raw = os.environ.get("ARTHDRISHTI_API_KEYS")
    if not raw and _is_production():
        # The well-known dev key is never accepted in production.
        return set()
    if not raw:
        logger.warning(
            "ARTHDRISHTI_API_KEYS not set — falling back to a single well-known dev key "
            f"('{_DEV_FALLBACK_KEY}') so local development and the README's examples work "
            "with zero setup. Set ARTHDRISHTI_API_KEYS (comma-separated) for any real deployment."
        )
        return {_DEV_FALLBACK_KEY}
    return {k.strip() for k in raw.split(",") if k.strip()}


def issue_token(api_key: str) -> dict:
    """Raises PermissionError for an invalid key — callers translate that
    to a 401, not a 500; this function itself has no HTTP awareness."""
    if api_key not in _valid_api_keys():
        raise PermissionError("Invalid API key.")
    now = int(time.time())
    payload = {"sub": "arthdrishti-client", "iat": now, "exp": now + _TOKEN_TTL_SECONDS}
    token = jwt.encode(payload, _SECRET, algorithm=_ALGORITHM)
    return {"access_token": token, "token_type": "bearer", "expires_in": _TOKEN_TTL_SECONDS}


def _decode(token: str) -> dict:
    return jwt.decode(token, _SECRET, algorithms=[_ALGORITHM])


# Token "typ" values that must never be accepted as an access credential.
_NON_ACCESS_TYPES = {"refresh", "wallet_challenge"}


def encode_jwt(payload: dict, ttl_seconds: int) -> str:
    """Sign a JWT with the shared secret. Used for user access/refresh
    tokens and short-lived wallet-ownership challenges."""
    now = int(time.time())
    return jwt.encode({**payload, "iat": now, "exp": now + ttl_seconds}, _SECRET, algorithm=_ALGORITHM)


def decode_jwt(token: str) -> dict:
    """Verify signature + expiry. Raises jwt.InvalidTokenError subclasses."""
    return _decode(token)


_bearer_scheme = HTTPBearer(
    scheme_name="ArthDrishtiBearer",
    description="Obtain a token via POST /auth/token with a valid API key, then pass it here.",
)


async def require_auth(credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme)) -> dict:
    """FastAPI dependency — attach via `dependencies=[Depends(require_auth)]`
    on any endpoint that needs a valid, unexpired token. Leave /health
    (and this module's own /auth/token) undecorated; everything else
    that touches real data should require it."""
    try:
        payload = _decode(credentials.credentials)
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Token expired — call /auth/token again.")
    except jwt.InvalidTokenError:
        raise HTTPException(401, "Invalid token.")
    if payload.get("typ") in _NON_ACCESS_TYPES:
        raise HTTPException(401, "Invalid token.")
    return payload
