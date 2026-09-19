"""
The user's own saved address book. Per the non-negotiable safety rule:
recipient addresses for AI-assisted sending are ONLY ever pulled from here
— never guessed, inferred, or auto-added by the AI.
"""
from __future__ import annotations
from dataclasses import dataclass


@dataclass
class Contact:
    name: str
    address: str
    chain: str = "ethereum"


class AddressBook:
    """In-memory per-session address book. A real deployment persists this
    per authenticated user; kept simple here so the safety logic is what
    gets tested, not the storage layer."""

    def __init__(self):
        self._contacts: dict[str, Contact] = {}

    def add(self, contact: Contact) -> None:
        self._contacts[contact.name.lower()] = contact

    def resolve(self, name: str) -> Contact | None:
        """The ONLY way an address can be produced for a natural-language
        send request. Returns None rather than guessing if the name isn't
        a saved contact — callers must treat None as "cannot proceed"."""
        return self._contacts.get(name.lower())

    def all(self) -> list[Contact]:
        return list(self._contacts.values())
