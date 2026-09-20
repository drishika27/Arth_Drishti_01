"""
Bank-provider abstraction.

Every provider — the built-in test bank today, a licensed Account Aggregator
(Setu, Finvu…) or Plaid later — implements the same small interface, so the
consent flow, sync, categorisation and UI never change when a live provider is
switched on. Providers only ever return an opaque access token: bank passwords,
OTPs and UPI PINs are never requested by, or visible to, ArthDrishti.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional, Protocol


@dataclass
class ProviderAccount:
    external_id: str
    name: str
    mask: str
    type: str                 # savings | checking | deposit | credit
    currency: str
    balance: Optional[float]


@dataclass
class ProviderTxn:
    external_id: str
    date: date
    description: str
    amount: float             # signed: negative = money out
    balance: Optional[float] = None


class BankProvider(Protocol):
    id: str
    name: str
    mode: str                 # "sandbox" | "live"

    def institutions(self) -> list[dict]: ...
    def consent_details(self, institution_id: str) -> dict: ...
    def grant_access(self, institution_id: str) -> str: ...
    def fetch_accounts(self, token: str) -> list[ProviderAccount]: ...
    def fetch_transactions(self, token: str, account_id: str, since: Optional[date]) -> list[ProviderTxn]: ...


class ProviderError(Exception):
    """The provider was unreachable or refused — message is safe to show the user."""


def registry() -> dict[str, BankProvider]:
    """Enabled providers. A live aggregator is added here once credentials exist."""
    from .sandbox import SandboxProvider
    return {"sandbox": SandboxProvider()}


def get_provider(provider_id: str) -> BankProvider:
    p = registry().get(provider_id)
    if p is None:
        raise ProviderError(f"Bank provider '{provider_id}' isn't available.")
    return p
