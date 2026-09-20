"""
Persistent data model. Every user-owned table carries `user_id`, and every
query in the API layer filters on it — that is the user-data isolation rule.

Manual entries, OCR receipts and bank transactions all land in ONE table
(`expenses`, distinguished by `source`) so analytics, budgets and AI
insights see a single, consistent picture of the user's money.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    Boolean, Date, DateTime, ForeignKey, Index, Numeric, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120), default="")
    password_hash: Mapped[str] = mapped_column(String(255))
    language: Mapped[str] = mapped_column(String(16), default="English")
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    monthly_budget: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class BankConnection(Base):
    """A user's consent-based link to one bank via a provider (sandbox, Plaid…).
    Only an opaque, provider-issued access token is kept (encrypted at rest).
    Bank passwords / OTPs / UPI PINs are never requested or stored."""
    __tablename__ = "bank_connections"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(32))
    institution_name: Mapped[str] = mapped_column(String(120), default="")
    status: Mapped[str] = mapped_column(String(16), default="active")   # active | error | revoked
    access_token_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    external_item_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    sync_cursor: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    accounts: Mapped[list["BankAccount"]] = relationship(
        back_populates="connection", cascade="all, delete-orphan")


class BankAccount(Base):
    __tablename__ = "bank_accounts"
    __table_args__ = (UniqueConstraint("connection_id", "external_id", name="uq_account_ext"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    connection_id: Mapped[str] = mapped_column(ForeignKey("bank_connections.id", ondelete="CASCADE"))
    external_id: Mapped[str] = mapped_column(String(128))
    name: Mapped[str] = mapped_column(String(120))
    mask: Mapped[str] = mapped_column(String(16), default="")
    type: Mapped[str] = mapped_column(String(32), default="checking")
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    balance: Mapped[Decimal | None] = mapped_column(Numeric(16, 2), nullable=True)
    balance_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    connection: Mapped[BankConnection] = relationship(back_populates="accounts")


class Receipt(Base):
    """One OCR attempt. The image itself is NOT stored — only the extracted
    text and result — so a failed run can be retried by re-uploading."""
    __tablename__ = "receipts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(255), default="")
    mime: Mapped[str] = mapped_column(String(64), default="")
    engine: Mapped[str] = mapped_column(String(32), default="")
    status: Mapped[str] = mapped_column(String(16), default="done")   # done | failed
    raw_text: Mapped[str] = mapped_column(Text, default="")
    extracted_json: Mapped[str] = mapped_column(Text, default="{}")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    expense_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Expense(Base):
    __tablename__ = "expenses"
    __table_args__ = (
        UniqueConstraint("user_id", "account_id", "external_id", name="uq_expense_external"),
        Index("ix_expense_user_date", "user_id", "date"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    source: Mapped[str] = mapped_column(String(16), default="manual")   # manual | ocr | bank
    kind: Mapped[str] = mapped_column(String(8), default="expense")     # expense | income
    merchant: Mapped[str] = mapped_column(String(200))
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))              # always positive
    tax: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    category: Mapped[str] = mapped_column(String(40), default="Other")
    category_source: Mapped[str] = mapped_column(String(16), default="manual")  # manual|rule|user_rule|ai|user
    date: Mapped[date] = mapped_column(Date)
    note: Mapped[str] = mapped_column(String(500), default="")
    account_id: Mapped[str | None] = mapped_column(
        ForeignKey("bank_accounts.id", ondelete="SET NULL"), nullable=True)
    external_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    raw_description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    receipt_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    user_edited: Mapped[bool] = mapped_column(Boolean, default=False)
    # "Deleting" a bank-imported row only hides it (the row stays so the next
    # sync's external_id de-duplication doesn't re-import it).
    ignored: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class MerchantRule(Base):
    """Learned from the user's own corrections: 'Zomato' -> 'Food', applied
    to every future import for that user."""
    __tablename__ = "merchant_rules"
    __table_args__ = (UniqueConstraint("user_id", "merchant_key", name="uq_merchant_rule"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    merchant_key: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(40))


class WalletLink(Base):
    """A crypto address the user has linked. Address only — never keys or
    seed phrases. `verified` means the user proved control by signing a
    challenge in their own wallet; otherwise it's watch-only."""
    __tablename__ = "wallet_links"
    __table_args__ = (UniqueConstraint("user_id", "address", "chain", name="uq_wallet_link"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    address: Mapped[str] = mapped_column(String(64))       # lowercase hex
    chain: Mapped[str] = mapped_column(String(24), default="ethereum")
    label: Mapped[str] = mapped_column(String(80), default="")
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
