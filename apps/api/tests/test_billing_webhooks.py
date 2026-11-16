import json
from datetime import timedelta

import pytest

from app.billing.webhooks import PermanentWebhookError, map_status
from app.models.billing import (
    BillingEvent, BillingEventStatus, CheckoutSession, CheckoutStatus, Payment, PaymentStatus, Subscription,
    SubscriptionStatus, TrialHistory,
)
from app.models.user import User
from tests.billing_helpers import (
    NOW, billing_settings, invoice_body, make_session, make_website, order_refund_body, post_webhook, register, sign,  # noqa: F401
    subscription_body,
)


@pytest.fixture
def setup(client, db_session, billing_settings):
    headers, org = register(client, "wh@example.com")
    user = db_session.query(User).filter(User.email == "wh@example.com").one()
    site = make_website(db_session, org)
    session = make_session(db_session, site, user.id)
    return site, session, user


def _sub(db_session, provider_id="1001"):
    return db_session.query(Subscription).filter(Subscription.provider_subscription_id == provider_id).one_or_none()


# --- signature -------------------------------------------------------------------------------

@pytest.mark.parametrize("signature", [None, "", "deadbeef", "A" * 64])
def test_a_bad_or_missing_signature_changes_nothing(client, db_session, setup, signature):
    site, session, _ = setup
    r = post_webhook(client, subscription_body(reference=session.reference), signature=signature)
    assert r.status_code == 401
    assert _sub(db_session) is None
    db_session.refresh(session)
    assert session.status == CheckoutStatus.pending
    assert db_session.query(BillingEvent).filter(BillingEvent.status == BillingEventStatus.rejected).count() >= 1


def test_a_valid_signature_over_a_different_body_is_rejected(client, db_session, setup):
    _, session, _ = setup
    raw = json.dumps(subscription_body(reference=session.reference)).encode()
    tampered = raw.replace(b"on_trial", b"active")
    assert client.post("/api/v1/billing/webhooks/lemonsqueezy", content=tampered, headers={"X-Signature": sign(raw)}).status_code == 401
    assert _sub(db_session) is None


def test_the_signature_check_is_case_insensitive_hex(client, setup):
    _, session, _ = setup
    raw = json.dumps(subscription_body(reference=session.reference)).encode()
    assert post_webhook(client, raw, signature=sign(raw).upper()).status_code == 200


def test_without_a_configured_secret_nothing_verifies(client, setup, monkeypatch, billing_settings):
    _, session, _ = setup
    monkeypatch.setattr(billing_settings, "lemonsqueezy_webhook_secret", None)
    assert post_webhook(client, subscription_body(reference=session.reference), signature="whatever").status_code == 401


# --- creating the subscription ---------------------------------------------------------------

def test_subscription_created_during_trial_unlocks_exactly_the_checked_out_project(client, db_session, setup):
    site, session, user = setup
    r = post_webhook(client, subscription_body(reference=session.reference))
    assert r.status_code == 200 and r.json()["status"] == "processed"

    sub = _sub(db_session)
    assert (sub.website_id, sub.organization_id, sub.user_id) == (site.id, site.organization_id, user.id)
    assert sub.status == SubscriptionStatus.trialing
    assert (sub.price_cents, sub.billing_interval.value) == (1500, "month")
    assert sub.trial_ends_at == NOW + timedelta(days=7) and sub.renews_at == NOW + timedelta(days=7)
    assert sub.customer_portal_url == "https://store.example/billing"
    db_session.refresh(session)
    assert session.status == CheckoutStatus.completed and session.subscription_id == sub.id
    trial = db_session.query(TrialHistory).filter(TrialHistory.website_id == site.id).one()
    assert (trial.outcome, trial.subscription_id) == ("active", sub.id)


def test_the_project_comes_from_our_checkout_record_never_from_custom_data(client, db_session, setup):
    """A payer cannot attach their subscription to someone else's project by editing custom data."""
    site, session, _ = setup
    _, other_org = register(client, "victim@example.com")
    victim = make_website(db_session, other_org, "victim.example")
    body = subscription_body(custom={"reference": session.reference, "project_id": str(victim.id)})
    post_webhook(client, body)
    assert _sub(db_session).website_id == site.id


def test_an_unknown_checkout_reference_is_recorded_for_review_not_applied(client, db_session, setup):
    r = post_webhook(client, subscription_body(reference="not-ours"))
    assert r.status_code == 200 and r.json()["status"] == "failed"  # permanent: the provider must not keep retrying
    assert _sub(db_session) is None
    event = db_session.query(BillingEvent).filter(BillingEvent.status == BillingEventStatus.failed).one()
    assert "checkout reference" in event.error


def test_a_second_paid_subscription_for_a_project_is_flagged_not_applied(client, db_session, setup):
    site, session, user = setup
    post_webhook(client, subscription_body(reference=session.reference))
    second = make_session(db_session, site, user.id)
    r = post_webhook(client, subscription_body(sub_id="1002", reference=second.reference))
    assert r.json()["status"] == "failed"
    assert _sub(db_session, "1002") is None
    assert db_session.query(Subscription).filter(Subscription.website_id == site.id).count() == 1
    assert "already has a live subscription" in db_session.query(BillingEvent).filter(BillingEvent.status == BillingEventStatus.failed).one().error


# --- idempotency and ordering ----------------------------------------------------------------

def test_an_exact_redelivery_is_a_noop(client, db_session, setup):
    _, session, _ = setup
    raw = json.dumps(subscription_body(reference=session.reference)).encode()
    first = post_webhook(client, raw)
    second = post_webhook(client, raw)
    assert (first.json()["status"], second.json()["status"]) == ("processed", "duplicate")
    assert db_session.query(Subscription).count() == 1
    assert db_session.query(BillingEvent).filter(BillingEvent.status == BillingEventStatus.processed).count() == 1


def test_an_older_event_never_overwrites_newer_state(client, db_session, setup):
    _, session, _ = setup
    post_webhook(client, subscription_body(reference=session.reference, updated=NOW))
    post_webhook(client, subscription_body(event="subscription_updated", status="active", reference=session.reference,
                                           updated=NOW + timedelta(days=7), trial_ends=None))
    stale = post_webhook(client, subscription_body(event="subscription_updated", status="on_trial", reference=session.reference,
                                                   updated=NOW + timedelta(hours=1)))
    assert stale.json()["status"] == "ignored"
    assert _sub(db_session).status == SubscriptionStatus.active


def test_an_update_may_arrive_before_the_creation_event(client, db_session, setup):
    """custom_data travels with every subscription event, so order does not matter."""
    _, session, _ = setup
    post_webhook(client, subscription_body(event="subscription_updated", status="active", reference=session.reference,
                                           updated=NOW + timedelta(days=7), trial_ends=None))
    post_webhook(client, subscription_body(event="subscription_created", status="on_trial", reference=session.reference, updated=NOW))
    assert _sub(db_session).status == SubscriptionStatus.active  # the older "created" did not roll it back
    assert db_session.query(Subscription).count() == 1


def test_an_invoice_before_its_subscription_is_retried_then_applied(client, db_session, setup):
    _, session, _ = setup
    invoice = json.dumps(invoice_body()).encode()
    assert post_webhook(client, invoice).status_code == 503  # provider will retry
    assert db_session.query(Payment).count() == 0

    post_webhook(client, subscription_body(reference=session.reference))
    retry = post_webhook(client, invoice)
    assert retry.status_code == 200 and retry.json()["status"] == "processed"
    assert db_session.query(Payment).one().amount_cents == 1500


# --- lifecycle -------------------------------------------------------------------------------

def test_trial_converts_to_paid_and_the_payment_is_recorded_once(client, db_session, setup):
    site, session, _ = setup
    post_webhook(client, subscription_body(reference=session.reference))
    later = NOW + timedelta(days=7, minutes=1)
    post_webhook(client, subscription_body(event="subscription_updated", status="active", reference=session.reference,
                                           updated=later, trial_ends=NOW + timedelta(days=7), renews=later + timedelta(days=30)))
    post_webhook(client, invoice_body(updated=later))
    post_webhook(client, invoice_body(event="subscription_payment_success", updated=later + timedelta(seconds=1)))  # same invoice again

    sub = _sub(db_session)
    assert sub.status == SubscriptionStatus.active
    payment = db_session.query(Payment).one()
    assert (payment.amount_cents, payment.status, payment.provider_payment_key) == (1500, PaymentStatus.paid, "invoice:9001")
    assert db_session.query(TrialHistory).filter(TrialHistory.website_id == site.id).one().outcome == "converted"


def test_cancelling_during_the_trial_keeps_access_until_the_end_date(client, db_session, setup):
    site, session, _ = setup
    post_webhook(client, subscription_body(reference=session.reference))
    post_webhook(client, subscription_body(event="subscription_cancelled", status="cancelled", cancelled=True, reference=session.reference,
                                           updated=NOW + timedelta(days=2), ends_at=NOW + timedelta(days=7)))
    sub = _sub(db_session)
    assert sub.status == SubscriptionStatus.cancelled and sub.ends_at == NOW + timedelta(days=7) and sub.cancelled_at is not None
    assert db_session.query(TrialHistory).filter(TrialHistory.website_id == site.id).one().outcome == "cancelled"


def test_an_active_subscription_flagged_cancelled_is_cancelled_locally(client, db_session, setup):
    _, session, _ = setup
    post_webhook(client, subscription_body(status="active", cancelled=True, reference=session.reference, trial_ends=None,
                                           ends_at=NOW + timedelta(days=20)))
    assert _sub(db_session).status == SubscriptionStatus.cancelled


def test_payment_failure_starts_a_grace_period_and_recovery_clears_it(client, db_session, setup):
    _, session, _ = setup
    post_webhook(client, subscription_body(status="active", reference=session.reference, trial_ends=None))
    t1 = NOW + timedelta(days=30)
    post_webhook(client, subscription_body(event="subscription_updated", status="past_due", reference=session.reference, updated=t1, trial_ends=None))
    post_webhook(client, invoice_body(event="subscription_payment_failed", invoice_id="9002", status="pending", reason="renewal", updated=t1))
    sub = _sub(db_session)
    assert sub.status == SubscriptionStatus.past_due and sub.grace_ends_at == t1 + timedelta(days=7)
    assert db_session.query(Payment).filter(Payment.provider_payment_key == "invoice:9002").one().status == PaymentStatus.failed

    t2 = t1 + timedelta(days=1)
    post_webhook(client, subscription_body(event="subscription_updated", status="active", reference=session.reference, updated=t2, trial_ends=None))
    post_webhook(client, invoice_body(event="subscription_payment_recovered", invoice_id="9002", reason="renewal", updated=t2))
    assert _sub(db_session).status == SubscriptionStatus.active and _sub(db_session).grace_ends_at is None
    assert db_session.query(Payment).filter(Payment.provider_payment_key == "invoice:9002").one().status == PaymentStatus.paid


@pytest.mark.parametrize("provider_status,local", [("paused", SubscriptionStatus.paused), ("unpaid", SubscriptionStatus.unpaid),
                                                    ("expired", SubscriptionStatus.expired)])
def test_other_provider_states_map_to_local_states(client, db_session, setup, provider_status, local):
    _, session, _ = setup
    post_webhook(client, subscription_body(status=provider_status, reference=session.reference, trial_ends=None))
    assert _sub(db_session).status == local


def test_a_new_event_name_does_not_matter_only_the_subscription_object_does(client, db_session, setup):
    _, session, _ = setup
    post_webhook(client, subscription_body(event="subscription_something_new", status="active", reference=session.reference, trial_ends=None))
    assert _sub(db_session).status == SubscriptionStatus.active


def test_unknown_provider_status_is_not_guessed():
    with pytest.raises(PermanentWebhookError):
        map_status("brand_new_status", False)


# --- refunds ---------------------------------------------------------------------------------

def _paid(client, session):
    post_webhook(client, subscription_body(status="active", reference=session.reference, trial_ends=None))
    post_webhook(client, invoice_body())


def test_a_full_refund_of_the_first_payment_ends_the_subscription(client, db_session, setup):
    _, session, _ = setup
    _paid(client, session)
    post_webhook(client, order_refund_body(updated=NOW + timedelta(days=1)))
    assert _sub(db_session).status == SubscriptionStatus.refunded
    payment = db_session.query(Payment).one()
    assert (payment.status, payment.refunded_cents) == (PaymentStatus.refunded, 1500)


def test_a_partial_refund_keeps_access(client, db_session, setup):
    _, session, _ = setup
    _paid(client, session)
    post_webhook(client, order_refund_body(refunded_amount=500, updated=NOW + timedelta(days=1)))
    assert _sub(db_session).status == SubscriptionStatus.active
    payment = db_session.query(Payment).one()
    assert (payment.status, payment.refunded_cents) == (PaymentStatus.partially_refunded, 500)


def test_a_refunded_subscription_frees_the_project_for_a_new_checkout(client, db_session, setup):
    site, session, user = setup
    _paid(client, session)
    post_webhook(client, order_refund_body(updated=NOW + timedelta(days=1)))
    fresh = make_session(db_session, site, user.id)
    post_webhook(client, subscription_body(sub_id="1002", reference=fresh.reference, order_id="5002"))
    assert _sub(db_session, "1002").status == SubscriptionStatus.trialing


def test_order_created_is_ignored_so_revenue_is_not_double_counted(client, db_session, setup):
    body = {"meta": {"event_name": "order_created", "test_mode": True},
            "data": {"type": "orders", "id": "5001", "attributes": {"total": 1500, "updated_at": "2026-11-16T10:00:00.000000Z"}}}
    r = post_webhook(client, body)
    assert r.json()["status"] == "ignored"
    assert db_session.query(Payment).count() == 0


def test_money_is_stored_as_integer_cents(client, db_session, setup):
    _, session, _ = setup
    _paid(client, session)
    assert isinstance(db_session.query(Payment).one().amount_cents, int)
    assert isinstance(_sub(db_session).price_cents, int)
