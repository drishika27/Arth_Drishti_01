"""
Password hashing, user tokens and at-rest encryption of provider tokens.

- Passwords: scrypt (stdlib — no extra dependency), per-user random salt,
  constant-time comparison. Plaintext passwords are never stored or logged.
- Tokens: short-lived access JWT (1h) + longer refresh JWT (14d), signed
  with the same JWT_SECRET as shared_engine.auth. `typ` distinguishes them
  so a refresh token can't be used as an access token.
- Field encryption: Fernet, keyed by DATA_ENCRYPTION_KEY. Used for the
  opaque bank-provider access tokens. (Bank passwords/OTPs/PINs are never
  collected at all, so there is nothing of that kind to encrypt.)
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import time
from collections import defaultdict, deque

from cryptography.fernet import Fernet, InvalidToken

from shared_engine.auth import encode_jwt, decode_jwt
from . import config

ACCESS_TTL = 3600
REFRESH_TTL = 14 * 24 * 3600

_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 2 ** 14, 8, 1


# ---- passwords -----------------------------------------------------------
def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=32)
    return "scrypt${}${}${}${}${}".format(
        _SCRYPT_N, _SCRYPT_R, _SCRYPT_P,
        base64.b64encode(salt).decode(), base64.b64encode(digest).decode())


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt_b64, digest_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
        actual = hashlib.scrypt(password.encode(), salt=salt, n=int(n), r=int(r), p=int(p), dklen=len(expected))
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


# ---- user tokens ---------------------------------------------------------
def issue_user_tokens(user_id: str) -> dict:
    return {
        "access_token": encode_jwt({"sub": user_id, "typ": "user"}, ACCESS_TTL),
        "refresh_token": encode_jwt({"sub": user_id, "typ": "refresh"}, REFRESH_TTL),
        "token_type": "bearer",
        "expires_in": ACCESS_TTL,
    }


# ---- at-rest encryption --------------------------------------------------
def _fernet() -> Fernet:
    seed = os.environ.get("DATA_ENCRYPTION_KEY", "").strip()
    if not seed:
        if config.is_production():
            raise RuntimeError("DATA_ENCRYPTION_KEY must be set when ARTHDRISHTI_ENV=production.")
        # Dev only: fall back to the JWT secret so local data survives restarts whenever
        # JWT_SECRET is stable. Not acceptable for production (hence the check above).
        seed = os.environ.get("JWT_SECRET", "dev-only-insecure-seed")
    # Any sufficiently random string works (e.g. Render's generateValue): derive a valid Fernet key from it.
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(seed.encode()).digest()))


def encrypt_secret(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_secret(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise ValueError("Stored credential could not be decrypted (wrong DATA_ENCRYPTION_KEY?)") from exc


# ---- login throttling ----------------------------------------------------
class AttemptLimiter:
    """Sliding-window limiter for failed logins, keyed by e.g. email+IP.
    In-memory: fine for one instance; use a shared store if scaled out."""

    def __init__(self, max_attempts: int = 8, window_seconds: int = 300):
        self.max_attempts = max_attempts
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def _prune(self, key: str) -> deque[float]:
        q = self._hits[key]
        cutoff = time.monotonic() - self.window
        while q and q[0] < cutoff:
            q.popleft()
        return q

    def blocked(self, key: str) -> bool:
        return len(self._prune(key)) >= self.max_attempts

    def record_failure(self, key: str) -> None:
        self._prune(key).append(time.monotonic())

    def reset(self, key: str) -> None:
        self._hits.pop(key, None)


login_limiter = AttemptLimiter()
