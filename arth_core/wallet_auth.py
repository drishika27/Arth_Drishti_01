"""
Sign-in with an Ethereum wallet (EIP-191 personal_sign, like "Sign-In with Ethereum").

The user proves they control an address by signing a one-time message in their
own wallet. The server never sees a private key or seed phrase — only the
signature, from which it recovers the signer's public address.

The challenge is stateless (a short-lived signed JWT carrying the exact message
and nonce), and each nonce can be used once, so a captured signature can't be replayed.
"""
from __future__ import annotations

import re
import secrets
import time
from datetime import datetime, timezone

import jwt
from eth_account import Account
from eth_account.messages import encode_defunct
from eth_utils import to_checksum_address

from shared_engine.auth import decode_jwt, encode_jwt
from .crypto import normalize_address

CHALLENGE_TTL = 300
_used_nonces: dict[str, float] = {}      # nonce -> expiry; per-process is enough for a single-worker deployment
_DOMAIN_RE = re.compile(r"^[A-Za-z0-9.\-:]{1,100}$")


def make_challenge(address: str, domain: str = "") -> dict:
    addr = normalize_address(address)                 # raises ValueError on a bad address
    if not _DOMAIN_RE.match(domain or ""):
        domain = "ArthDrishti"
    nonce = secrets.token_hex(16)
    issued = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    message = (
        f"{domain} wants you to sign in with your Ethereum account:\n"
        f"{to_checksum_address(addr)}\n\n"
        "Sign this message to prove you own this wallet. It does not send a transaction, "
        "costs no gas, and gives ArthDrishti no access to your funds.\n\n"
        f"Nonce: {nonce}\nIssued At: {issued}\nValid for: 5 minutes"
    )
    token = encode_jwt({"typ": "wallet_challenge", "addr": addr, "nonce": nonce, "msg": message}, CHALLENGE_TTL)
    return {"message": message, "token": token}


def verify_challenge(address: str, signature: str, token: str) -> str:
    """Returns the verified lowercase address, or raises ValueError with a user-facing reason."""
    addr = normalize_address(address)
    try:
        claims = decode_jwt(token)
    except jwt.InvalidTokenError:
        raise ValueError("The sign-in request expired. Please try again.")
    if claims.get("typ") != "wallet_challenge" or claims.get("addr") != addr:
        raise ValueError("That sign-in request doesn't match this wallet.")
    now = time.time()
    for n in [n for n, exp in _used_nonces.items() if exp < now]:
        del _used_nonces[n]
    if claims["nonce"] in _used_nonces:
        raise ValueError("That sign-in request was already used. Please try again.")
    try:
        signer = Account.recover_message(encode_defunct(text=claims["msg"]), signature=signature)
    except Exception:
        raise ValueError("That signature isn't valid.")
    if signer.lower() != addr:
        raise ValueError("The signature doesn't match this wallet address.")
    _used_nonces[claims["nonce"]] = now + CHALLENGE_TTL
    return addr
