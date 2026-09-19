"""
Safety tests for batch approval revocation (arth_raksha/backend/revoke.py)
— mirrors tests/test_transaction_safety.py's pattern for the send flow.
Revoking is the second highest-stakes code path in the platform (it still
produces a real signable transaction), so it gets the same guarantees:
never signs, never broadcasts, and a draft can't be handed to a wallet
before explicit confirmation.
"""
from __future__ import annotations

import pytest

from arth_raksha.backend.revoke import draft_batch_revoke, draft_revoke

TOKEN = "0xdAC17F958D2ee523a2206206994597C13D831ec7"
SPENDER = "0x1111111254EEB25477B68fb85Ed929f73A960582"


def test_draft_revoke_produces_real_erc20_approve_zero_calldata():
    draft = draft_revoke(TOKEN, SPENDER)
    # The real, well-known approve(address,uint256) selector, verified
    # independently via Web3.keccak(text="approve(address,uint256)")[:4].
    assert draft.calldata.startswith("0x095ea7b3")
    # ...and the trailing 32 bytes (the `value` argument) must be all
    # zero — this is what makes it a *revoke*, not a re-approval.
    assert draft.calldata.endswith("0" * 64)
    assert SPENDER[2:].lower() in draft.calldata.lower()


def test_draft_cannot_be_handed_to_wallet_before_confirmation():
    draft = draft_revoke(TOKEN, SPENDER)
    with pytest.raises(RuntimeError):
        draft.to_wallet_provider_payload()


def test_confirmed_payload_never_contains_a_private_key_or_signature():
    draft = draft_revoke(TOKEN, SPENDER)
    draft.confirm()
    payload = draft.to_wallet_provider_payload()
    keys = {k.lower() for k in payload.keys()}
    assert "privatekey" not in keys and "private_key" not in keys and "signature" not in keys
    assert "from" not in keys  # the wallet provider fills this in client-side, never this backend


def test_batch_revoke_drafts_are_independent_and_all_unconfirmed():
    approvals = [
        {"token_address": TOKEN, "spender_address": SPENDER},
        {"token_address": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48", "spender_address": SPENDER},
    ]
    drafts = draft_batch_revoke(approvals)
    assert len(drafts) == 2
    assert all(d.confirmed is False for d in drafts)
    # confirming one must not confirm the other
    drafts[0].confirm()
    assert drafts[0].confirmed is True
    assert drafts[1].confirmed is False
