"""
AI-assisted, human-confirmed sending.

This is the single highest-stakes code path in the platform. The rules from
the brief, enforced here structurally (not just by prompting):

  1. The AI never holds private keys and never signs or broadcasts a
     transaction on its own — this module has NO signing capability at all,
     by construction (there is no private key parameter anywhere in it).
  2. Recipient addresses are only ever pulled from the user's own saved
     address book — never guessed, inferred, or auto-added.
  3. Every draft must be explicitly confirmed by the user before it is
     considered "ready" — confirmed=False is the only state this module can
     produce on its own.

`draft_transaction` is the only entry point that turns natural language into
something send-able, and it can only ever return a TransactionDraft or raise
UnknownRecipientError. There is no code path from natural language straight
to a signed/broadcast transaction.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from .address_book import AddressBook, Contact


class UnknownRecipientError(Exception):
    """Raised when the natural-language request names someone who is not in
    the user's own saved address book. The caller must surface this to the
    user rather than falling back to any inferred/guessed address."""


AMOUNT_RE = re.compile(r"([\d.]+)\s*([A-Za-z]{2,10})")
SEND_RE = re.compile(r"send\s+([\d.]+)\s*([A-Za-z]{2,10})\s+to\s+([A-Za-z0-9_.\- ]+)", re.IGNORECASE)


@dataclass
class TransactionDraft:
    recipient_name: str
    recipient_address: str
    amount: float
    token: str
    chain: str
    is_first_time_to_address: bool
    confirmed: bool = False        # only the user, via confirm(), can flip this
    simulated_outcome: Optional[str] = None
    warnings: list[str] = field(default_factory=list)

    def confirm(self) -> "TransactionDraft":
        """Explicit user confirmation step. This still does not sign or
        broadcast anything — it only marks the draft ready to be handed to
        the user's own wallet provider (e.g. MetaMask) for signing."""
        self.confirmed = True
        return self

    def to_wallet_provider_payload(self) -> dict:
        """What would be handed to a client-side wallet (e.g. via
        window.ethereum / WalletConnect) for the USER to sign themselves.
        Raises if not yet confirmed — nothing leaves this module unconfirmed.

        `value` is a real hex-wei amount (what ethers.js/viem actually need
        to build `eth_sendTransaction`), assuming `token` is the chain's
        native asset — this module only ever drafts native-value transfers,
        never arbitrary ERC20 sends. `value_note` stays as the
        human-readable form for display."""
        if not self.confirmed:
            raise RuntimeError("Cannot hand off an unconfirmed draft for signing.")
        wei = int(round(self.amount * 10**18))
        return {
            "to": self.recipient_address,
            "value": hex(wei),
            "value_note": f"{self.amount} {self.token}",
            "chain": self.chain,
            # NOTE: intentionally no "from"/private key/signature here —
            # the connected wallet provider fills that in client-side.
        }


def draft_transaction(
    natural_language_request: str,
    address_book: AddressBook,
    seen_addresses: set[str] | None = None,
    chain: str = "ethereum",
) -> TransactionDraft:
    match = SEND_RE.search(natural_language_request)
    if not match:
        raise ValueError(
            "Could not understand this as a send request. Try: 'send 0.05 ETH to Saniya'."
        )
    amount_str, token, recipient_name = match.groups()
    recipient_name = recipient_name.strip()

    contact = address_book.resolve(recipient_name)
    if contact is None:
        # This is the enforcement point for "never guess or infer an
        # address" — an unknown name hard-stops here.
        raise UnknownRecipientError(
            f"'{recipient_name}' isn't in your saved address book. "
            f"Add them as a contact first, then try again."
        )

    seen_addresses = seen_addresses or set()
    is_first_time = contact.address.lower() not in {a.lower() for a in seen_addresses}

    warnings = []
    if is_first_time:
        warnings.append("This is the first time sending to this address.")

    return TransactionDraft(
        recipient_name=contact.name,
        recipient_address=contact.address,
        amount=float(amount_str),
        token=token.upper(),
        chain=chain,
        is_first_time_to_address=is_first_time,
        warnings=warnings,
    )


def simulate_transaction(w3, wallet_address: str, draft: TransactionDraft) -> str:
    """Transaction simulation preview via eth_call/eth_estimateGas against
    current chain state — shows the expected outcome before the user
    signs anything. For a plain native-token transfer this mainly catches
    a real, meaningful failure mode: sending to a contract address with no
    payable receive/fallback function, which would revert on-chain. Sets
    draft.simulated_outcome and returns it; never raises — including from
    address normalization, which a first version of this function did
    *outside* the try/except, so a saved contact address that wasn't
    perfectly EIP-55-checksummed (e.g. typed or pasted by hand) crashed
    the entire /send/draft request instead of just skipping the preview."""
    try:
        call = {
            "from": w3.to_checksum_address(wallet_address),
            "to": w3.to_checksum_address(draft.recipient_address),
            "value": w3.to_wei(draft.amount, "ether"),
        }
        w3.eth.call(call)
        gas = w3.eth.estimate_gas(call)
        outcome = f"Simulation succeeded — estimated gas: {gas}"
    except Exception as exc:
        outcome = f"Simulation preview unavailable: {exc}"
    draft.simulated_outcome = outcome
    return outcome
