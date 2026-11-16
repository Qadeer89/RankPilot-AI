"""Per-project subscriptions (commercial system, docs/COMMERCIAL_SYSTEM.md).

One subscription unlocks exactly one project (a `Website`). Money is always
integer cents. Billing history must outlive the organization / website / user
it was about (same rule as UsageRecord, RP13-020), so those links are
SET NULL and never cascade-delete a payment record.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class BillingInterval(str, enum.Enum):
    month = "month"
    year = "year"


class SubscriptionProvider(str, enum.Enum):
    lemonsqueezy = "lemonsqueezy"
    # A grant by the Super Admin (existing projects, support cases). Price 0,
    # never counted as revenue.
    complimentary = "complimentary"


class SubscriptionStatus(str, enum.Enum):
    trialing = "trialing"
    active = "active"
    past_due = "past_due"
    unpaid = "unpaid"
    paused = "paused"
    cancelled = "cancelled"  # may still be entitled until `ends_at`
    expired = "expired"
    refunded = "refunded"


# A subscription in one of these states still "occupies" its project: a second
# one for the same project is refused (partial unique index below).
LIVE_STATUSES = (
    SubscriptionStatus.trialing,
    SubscriptionStatus.active,
    SubscriptionStatus.past_due,
    SubscriptionStatus.unpaid,
    SubscriptionStatus.paused,
    SubscriptionStatus.cancelled,
)


def _fk(table: str, *, nullable: bool = True, ondelete: str = "SET NULL", index: bool = True):
    return mapped_column(UUID(as_uuid=True), ForeignKey(f"{table}.id", ondelete=ondelete), nullable=nullable, index=index)


class Subscription(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "subscriptions"
    __table_args__ = (
        # At most one live subscription may unlock a given project.
        Index(
            "uq_subscription_live_per_website",
            "website_id",
            unique=True,
            postgresql_where=text("website_id IS NOT NULL AND status NOT IN ('expired', 'refunded')"),
        ),
        Index(
            "uq_subscription_provider_ref",
            "provider",
            "provider_subscription_id",
            unique=True,
            postgresql_where=text("provider_subscription_id IS NOT NULL"),
        ),
    )

    organization_id: Mapped[uuid.UUID | None] = _fk("organizations")
    user_id: Mapped[uuid.UUID | None] = _fk("users")  # the purchaser
    website_id: Mapped[uuid.UUID | None] = _fk("websites")  # the project it unlocks

    provider: Mapped[SubscriptionProvider] = mapped_column(
        Enum(SubscriptionProvider, name="subscription_provider"), nullable=False
    )
    provider_customer_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    provider_subscription_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    provider_order_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    provider_product_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    provider_variant_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    provider_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # The provider's own timestamp for the state we hold: older events never overwrite newer state.
    provider_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    customer_portal_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    update_payment_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[SubscriptionStatus] = mapped_column(
        Enum(SubscriptionStatus, name="subscription_status"), nullable=False, index=True
    )
    billing_interval: Mapped[BillingInterval] = mapped_column(
        Enum(BillingInterval, name="billing_interval"), nullable=False
    )
    # The price agreed at purchase; later price changes never rewrite it.
    price_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)

    trial_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    trial_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    renews_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    grace_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    trial_reminder_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # One replacement per subscription lifetime (a Super Admin can raise the limit).
    replacements_used: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    replacement_limit: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class PaymentStatus(str, enum.Enum):
    paid = "paid"
    failed = "failed"
    pending = "pending"
    refunded = "refunded"
    partially_refunded = "partially_refunded"


class Payment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One charge (initial order, renewal or failed attempt). Immutable history:
    a refund updates the same row's status/refunded amount, rows are never deleted."""

    __tablename__ = "payments"

    subscription_id: Mapped[uuid.UUID | None] = _fk("subscriptions")
    organization_id: Mapped[uuid.UUID | None] = _fk("organizations")
    user_id: Mapped[uuid.UUID | None] = _fk("users")
    website_id: Mapped[uuid.UUID | None] = _fk("websites")
    provider: Mapped[SubscriptionProvider] = mapped_column(
        Enum(SubscriptionProvider, name="subscription_provider", create_type=False), nullable=False
    )
    # "order:<id>" or "invoice:<id>": makes recording the same payment twice impossible.
    provider_payment_key: Mapped[str] = mapped_column(String(96), unique=True, nullable=False)
    provider_order_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    provider_invoice_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    status: Mapped[PaymentStatus] = mapped_column(Enum(PaymentStatus, name="payment_status"), nullable=False, index=True)
    refunded_cents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    billing_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    billing_interval: Mapped[str | None] = mapped_column(String(8), nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    refunded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    test_mode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class BillingEventStatus(str, enum.Enum):
    received = "received"
    processed = "processed"
    ignored = "ignored"
    failed = "failed"
    rejected = "rejected"  # signature did not verify


class BillingEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Every provider webhook delivery, for idempotency and for the admin webhook history."""

    __tablename__ = "billing_events"

    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    # sha256 of the raw signed body: an exact re-delivery is recognised and never processed twice.
    event_key: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    event_name: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    provider_object_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    provider_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[BillingEventStatus] = mapped_column(
        Enum(BillingEventStatus, name="billing_event_status"), nullable=False, index=True
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    subscription_id: Mapped[uuid.UUID | None] = _fk("subscriptions")
    payload_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    test_mode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class CheckoutStatus(str, enum.Enum):
    pending = "pending"
    completed = "completed"
    expired = "expired"
    cancelled = "cancelled"
    failed = "failed"


class CheckoutSession(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "checkout_sessions"
    __table_args__ = (
        # No second pending checkout for the same project.
        Index(
            "uq_checkout_pending_per_website",
            "website_id",
            unique=True,
            postgresql_where=text("website_id IS NOT NULL AND status = 'pending'"),
        ),
    )

    organization_id: Mapped[uuid.UUID | None] = _fk("organizations")
    user_id: Mapped[uuid.UUID | None] = _fk("users")
    website_id: Mapped[uuid.UUID | None] = _fk("websites")
    billing_interval: Mapped[BillingInterval] = mapped_column(
        Enum(BillingInterval, name="billing_interval", create_type=False), nullable=False
    )
    variant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    expected_price_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    with_trial: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Random value sent to the provider as custom data and echoed back in the webhook.
    reference: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    status: Mapped[CheckoutStatus] = mapped_column(
        Enum(CheckoutStatus, name="checkout_status"), default=CheckoutStatus.pending, nullable=False
    )
    checkout_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    subscription_id: Mapped[uuid.UUID | None] = _fk("subscriptions")
    test_mode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class TrialHistory(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A project gets one free trial, ever: replacing its subscription or re-subscribing does not reset it."""

    __tablename__ = "trial_history"
    __table_args__ = (UniqueConstraint("website_id", name="uq_trial_history_website"),)

    website_id: Mapped[uuid.UUID | None] = _fk("websites")
    organization_id: Mapped[uuid.UUID | None] = _fk("organizations")
    subscription_id: Mapped[uuid.UUID | None] = _fk("subscriptions")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    outcome: Mapped[str] = mapped_column(String(16), default="active", nullable=False)  # active|converted|cancelled|expired
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ProjectReplacement(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Append-only record of a subscription being moved to another project."""

    __tablename__ = "project_replacements"

    subscription_id: Mapped[uuid.UUID | None] = _fk("subscriptions")
    user_id: Mapped[uuid.UUID | None] = _fk("users")
    from_website_id: Mapped[uuid.UUID | None] = _fk("websites")
    to_website_id: Mapped[uuid.UUID | None] = _fk("websites")
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    admin_override: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
