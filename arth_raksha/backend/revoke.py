"""
Batch approval revocation — drafting only, same non-negotiable rules as
transaction.py: this module has NO signing capability by construction (no
private-key parameter exists anywhere in it), and a draft can only reach
`to_wallet_provider_payload()` after an explicit `confirm()`.

A revoke is a direct call to the TOKEN contract's own `approve(spender, 0)`
— unlike a send, it never needs the user's address book (the target is
already a known, on-chain approval the wallet itself made; there is no
"recipient" to look up or guess).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from web3 import Web3

# Only the one function this module ever needs to encode.
_ERC20_APPROVE_ABI = [{
    "constant": False,
    "inputs": [{"name": "spender", "type": "address"}, {"name": "value", "type": "uint256"}],
    "name": "approve",
    "outputs": [{"name": "", "type": "bool"}],
    "type": "function",
}]

_w3_offline = Web3()  # ABI encoding is pure/local — no RPC connection needed for this


@dataclass
class RevokeDraft:
    token_address: str
    spender_address: str
    chain: str
    calldata: str
    confirmed: bool = False
    simulated_outcome: Optional[str] = None
    warnings: list[str] = field(default_factory=list)

    def confirm(self) -> "RevokeDraft":
        self.confirmed = True
        return self

    def to_wallet_provider_payload(self) -> dict:
        """What gets handed to the user's own wallet (MetaMask/WalletConnect)
        to sign. Raises if not yet confirmed — mirrors
        transaction.py::TransactionDraft.to_wallet_provider_payload exactly."""
        if not self.confirmed:
            raise RuntimeError("Cannot hand off an unconfirmed revoke draft for signing.")
        return {
            "to": self.token_address,
            "data": self.calldata,
            "value": "0x0",
            "value_note": "0 ETH (contract call: sets this spender's allowance to zero)",
            "chain": self.chain,
            # NOTE: intentionally no "from"/private key/signature here — same
            # contract as transaction.py's payload.
        }


def draft_revoke(token_address: str, spender_address: str, chain: str = "ethereum") -> RevokeDraft:
    token = _w3_offline.eth.contract(address=Web3.to_checksum_address(token_address), abi=_ERC20_APPROVE_ABI)
    calldata = token.encode_abi(abi_element_identifier="approve", args=[Web3.to_checksum_address(spender_address), 0])
    return RevokeDraft(
        token_address=Web3.to_checksum_address(token_address),
        spender_address=Web3.to_checksum_address(spender_address),
        chain=chain,
        calldata=calldata,
    )


def draft_batch_revoke(approvals: list[dict], chain: str = "ethereum") -> list[RevokeDraft]:
    """`approvals`: list of {"token_address": ..., "spender_address": ...}.
    One independent draft per approval — a batch is just "several drafts
    the user reviews and signs together in their wallet," never a single
    multi-call this backend assembles and signs on their behalf."""
    return [draft_revoke(a["token_address"], a["spender_address"], chain=chain) for a in approvals]


def simulate_revoke(w3, wallet_address: str, draft: RevokeDraft) -> str:
    """Transaction simulation preview: calls eth_call against current
    chain state with the exact calldata that would be signed, so a revert
    (e.g. a non-standard token, or a spender address that isn't actually
    approved) is caught and shown *before* the user signs anything —
    never after. Sets draft.simulated_outcome and returns it. Never
    raises: a simulation failure is itself useful information, recorded
    as the outcome rather than propagated as an exception — including a
    failure to checksum-normalize `wallet_address`, which an earlier
    version of this function did outside the try/except (same bug as
    transaction.py::simulate_transaction, found the same way: a
    real, hand-typed address that wasn't perfectly EIP-55-checksummed
    crashed the whole /revoke/draft request instead of just skipping
    the preview)."""
    try:
        call = {"from": Web3.to_checksum_address(wallet_address), "to": draft.token_address, "data": draft.calldata}
        w3.eth.call(call)
        gas = w3.eth.estimate_gas(call)
        outcome = f"Simulation succeeded — estimated gas: {gas}"
    except Exception as exc:
        outcome = f"Simulation failed — this transaction would likely revert: {exc}"
    draft.simulated_outcome = outcome
    return outcome
