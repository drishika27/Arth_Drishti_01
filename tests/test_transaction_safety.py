"""
The highest-stakes tests in the codebase: the transaction-drafting flow
must never be able to send to an unsaved address, and must never produce
a signed/broadcast transaction on its own.
"""
import pytest
from arth_raksha.backend.address_book import AddressBook, Contact
from arth_raksha.backend.transaction import draft_transaction, UnknownRecipientError

def test_unknown_recipient_is_refused_not_guessed():
    book = AddressBook()
    with pytest.raises(UnknownRecipientError):
        draft_transaction("send 0.05 ETH to Saniya", book)

def test_known_recipient_drafts_correctly_from_address_book_only():
    book = AddressBook()
    book.add(Contact(name="Saniya", address="0xaBC000000000000000000000000000000000DEaD"))
    draft = draft_transaction("send 0.05 ETH to Saniya", book)
    assert draft.recipient_address == "0xaBC000000000000000000000000000000000DEaD"
    assert draft.amount == 0.05
    assert draft.token == "ETH"
    assert draft.confirmed is False  # never auto-confirmed

def test_draft_cannot_be_handed_to_wallet_before_confirmation():
    book = AddressBook()
    book.add(Contact(name="Saniya", address="0xaBC000000000000000000000000000000000DEaD"))
    draft = draft_transaction("send 0.05 ETH to Saniya", book)
    with pytest.raises(RuntimeError):
        draft.to_wallet_provider_payload()

def test_confirmed_payload_never_contains_a_private_key_or_signature():
    book = AddressBook()
    book.add(Contact(name="Saniya", address="0xaBC000000000000000000000000000000000DEaD"))
    draft = draft_transaction("send 0.05 ETH to Saniya", book)
    draft.confirm()
    payload = draft.to_wallet_provider_payload()
    keys = {k.lower() for k in payload.keys()}
    assert "privatekey" not in keys and "private_key" not in keys and "signature" not in keys

def test_first_time_address_is_flagged():
    book = AddressBook()
    book.add(Contact(name="Saniya", address="0xaBC000000000000000000000000000000000DEaD"))
    draft = draft_transaction("send 0.05 ETH to Saniya", book, seen_addresses=set())
    assert draft.is_first_time_to_address is True
    assert any("first time" in w.lower() for w in draft.warnings)

def test_not_first_time_when_address_previously_seen():
    book = AddressBook()
    book.add(Contact(name="Saniya", address="0xaBC000000000000000000000000000000000DEaD"))
    draft = draft_transaction(
        "send 0.05 ETH to Saniya", book,
        seen_addresses={"0xabc000000000000000000000000000000000dead"},
    )
    assert draft.is_first_time_to_address is False
