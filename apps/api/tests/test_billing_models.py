"""Phase 1: the data model enforces the commercial rules by itself (a bug in a
service cannot violate them), and plan/price arithmetic is centralized."""

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from app.billing.plans import all_plans, annual_saving_cents, get_plan
from app.models.billing import (
    BillingEvent,
    BillingEventStatus,
    BillingInterval,
    CheckoutSession,
    CheckoutStatus,
    Payment,
    PaymentStatus,
    Subscription,
    SubscriptionProvider,
    SubscriptionStatus,
    TrialHistory,
)
from app.models.organization import Organization
from app.models.website import Website


def _site(db_session):
    org = Organization(name="Bill Org", slug=f"bill-{uuid.uuid4().hex[:8]}")
    db_session.add(org)
    db_session.flush()
    site = Website(organization_id=org.id, canonical_url="https://a.example/", hostname="a.example", display_name="A")
    db_session.add(site)
    db_session.flush()
    return org, site


def _sub(org, site, *, status=SubscriptionStatus.active, provider_id=None, interval=BillingInterval.month):
    return Subscription(
        organization_id=org.id, website_id=site.id, provider=SubscriptionProvider.lemonsqueezy,
        provider_subscription_id=provider_id or uuid.uuid4().hex[:10], status=status, billing_interval=interval,
        price_cents=1500 if interval == BillingInterval.month else 15000,
    )


def test_plan_prices_are_integer_cents_and_centralized():
    month, year = get_plan(BillingInterval.month), get_plan(BillingInterval.year)
    assert (month.price_cents, year.price_cents) == (1500, 15000)
    assert month.currency == year.currency == "USD"
    assert month.trial_days == year.trial_days == 7
    assert [p.interval for p in all_plans()] == [BillingInterval.month, BillingInterval.year]


def test_annual_plan_economics_match_the_approved_offer():
    year = get_plan(BillingInterval.year)
    assert year.monthly_equivalent_cents == 1250  # $12.50 a month
    assert annual_saving_cents() == 3000  # $30 saved = two months free
    assert get_plan(BillingInterval.month).annual_equivalent_cents == 18000
    assert year.annual_equivalent_cents == 15000


def test_one_live_subscription_per_project(db_session):
    org, site = _site(db_session)
    db_session.add(_sub(org, site))
    db_session.flush()
    db_session.add(_sub(org, site, status=SubscriptionStatus.trialing))
    with pytest.raises(IntegrityError):
        db_session.flush()


@pytest.mark.parametrize("live", [SubscriptionStatus.trialing, SubscriptionStatus.past_due, SubscriptionStatus.cancelled,
                                  SubscriptionStatus.paused, SubscriptionStatus.unpaid])
def test_a_cancelled_or_past_due_subscription_still_occupies_its_project(db_session, live):
    org, site = _site(db_session)
    db_session.add(_sub(org, site, status=live))
    db_session.flush()
    db_session.add(_sub(org, site))
    with pytest.raises(IntegrityError):
        db_session.flush()


@pytest.mark.parametrize("finished", [SubscriptionStatus.expired, SubscriptionStatus.refunded])
def test_a_finished_subscription_frees_the_project_for_a_new_one(db_session, finished):
    org, site = _site(db_session)
    db_session.add(_sub(org, site, status=finished))
    db_session.flush()
    db_session.add(_sub(org, site))
    db_session.flush()  # allowed


def test_two_projects_can_each_have_their_own_subscription(db_session):
    org, a = _site(db_session)
    b = Website(organization_id=org.id, canonical_url="https://b.example/", hostname="b.example", display_name="B")
    db_session.add(b)
    db_session.flush()
    db_session.add_all([_sub(org, a), _sub(org, b, interval=BillingInterval.year)])
    db_session.flush()


def test_a_provider_subscription_id_can_only_be_stored_once(db_session):
    org, a = _site(db_session)
    _, b = _site(db_session)
    db_session.add(_sub(org, a, provider_id="999"))
    db_session.flush()
    db_session.add(_sub(org, b, provider_id="999"))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_only_one_pending_checkout_per_project(db_session):
    org, site = _site(db_session)

    def checkout(status=CheckoutStatus.pending):
        return CheckoutSession(organization_id=org.id, website_id=site.id, billing_interval=BillingInterval.month,
                               variant_id="1", expected_price_cents=1500, reference=uuid.uuid4().hex, status=status)

    db_session.add(checkout(CheckoutStatus.expired))
    db_session.add(checkout(CheckoutStatus.completed))
    db_session.add(checkout())
    db_session.flush()  # finished checkouts do not count
    db_session.add(checkout())
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_a_project_has_at_most_one_trial_record(db_session):
    org, site = _site(db_session)
    now = datetime.now(timezone.utc)
    db_session.add(TrialHistory(website_id=site.id, organization_id=org.id, started_at=now))
    db_session.flush()
    db_session.add(TrialHistory(website_id=site.id, organization_id=org.id, started_at=now))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_the_same_payment_cannot_be_recorded_twice(db_session):
    org, site = _site(db_session)

    def payment():
        return Payment(organization_id=org.id, website_id=site.id, provider=SubscriptionProvider.lemonsqueezy,
                       provider_payment_key="order:1", amount_cents=1500, status=PaymentStatus.paid)

    db_session.add(payment())
    db_session.flush()
    db_session.add(payment())
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_an_identical_webhook_delivery_is_recognised(db_session):
    def event():
        return BillingEvent(provider="lemonsqueezy", event_key="abc123", status=BillingEventStatus.received)

    db_session.add(event())
    db_session.flush()
    db_session.add(event())
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_billing_history_survives_deleting_the_project(db_session):
    org, site = _site(db_session)
    sub = _sub(org, site)
    db_session.add(sub)
    db_session.flush()
    db_session.add(Payment(subscription_id=sub.id, organization_id=org.id, website_id=site.id,
                           provider=SubscriptionProvider.lemonsqueezy, provider_payment_key="order:7",
                           amount_cents=1500, status=PaymentStatus.paid))
    db_session.flush()

    db_session.delete(site)
    db_session.flush()
    db_session.expire_all()

    kept = db_session.query(Payment).filter(Payment.provider_payment_key == "order:7").one()
    assert kept.website_id is None and kept.amount_cents == 1500
    assert db_session.get(Subscription, sub.id).website_id is None
