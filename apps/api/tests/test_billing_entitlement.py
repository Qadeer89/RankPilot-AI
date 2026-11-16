import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.billing import entitlement
from app.billing.entitlement import EntitlementRequired, allowed, check, evaluate
from app.config import get_settings
from app.models.billing import BillingInterval, Subscription, SubscriptionProvider, SubscriptionStatus
from app.models.organization import Organization
from app.models.website import Website

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)


def _site(db_session, host="e.example"):
    org = Organization(name="Ent Org", slug=f"ent-{uuid.uuid4().hex[:8]}")
    db_session.add(org)
    db_session.flush()
    site = Website(organization_id=org.id, canonical_url=f"https://{host}/", hostname=host, display_name=host)
    db_session.add(site)
    db_session.flush()
    return site


def _sub(db_session, site, status, *, provider=SubscriptionProvider.lemonsqueezy, **fields):
    sub = Subscription(organization_id=site.organization_id, website_id=site.id, provider=provider,
                       provider_subscription_id=uuid.uuid4().hex[:10] if provider == SubscriptionProvider.lemonsqueezy else None,
                       status=status, billing_interval=BillingInterval.month, price_cents=1500, **fields)
    db_session.add(sub)
    db_session.flush()
    return sub


def test_no_subscription_means_not_entitled(db_session):
    result = evaluate(db_session, _site(db_session), now=NOW)
    assert (result.entitled, result.reason) == (False, "no_subscription")


@pytest.mark.parametrize(
    "status,fields,entitled,reason",
    [
        (SubscriptionStatus.trialing, dict(trial_ends_at=NOW + timedelta(days=3)), True, "trial"),
        (SubscriptionStatus.trialing, dict(trial_ends_at=NOW - timedelta(hours=5)), True, "trial"),          # provider a little late
        (SubscriptionStatus.trialing, dict(trial_ends_at=NOW - timedelta(days=2)), False, "trial_ended"),
        (SubscriptionStatus.active, dict(renews_at=NOW + timedelta(days=9)), True, "active"),
        (SubscriptionStatus.cancelled, dict(ends_at=NOW + timedelta(days=9)), True, "cancelled_until_end"),
        (SubscriptionStatus.cancelled, dict(ends_at=NOW - timedelta(seconds=1)), False, "expired"),
        (SubscriptionStatus.cancelled, dict(), False, "expired"),
        (SubscriptionStatus.past_due, dict(grace_ends_at=NOW + timedelta(days=2)), True, "grace_period"),
        (SubscriptionStatus.past_due, dict(grace_ends_at=NOW - timedelta(days=1)), False, "payment_overdue"),
        (SubscriptionStatus.past_due, dict(), False, "payment_overdue"),
        (SubscriptionStatus.unpaid, dict(), False, "unpaid"),
        (SubscriptionStatus.paused, dict(), False, "paused"),
        (SubscriptionStatus.expired, dict(), False, "expired"),
        (SubscriptionStatus.refunded, dict(), False, "refunded"),
    ],
)
def test_entitlement_policy_per_state(db_session, status, fields, entitled, reason):
    site = _site(db_session)
    _sub(db_session, site, status, **fields)
    result = evaluate(db_session, site, now=NOW)
    assert (result.entitled, result.reason) == (entitled, reason)
    assert isinstance(result.message, str) and result.message


def test_a_complimentary_grant_entitles_but_expires(db_session):
    site = _site(db_session)
    _sub(db_session, site, SubscriptionStatus.active, provider=SubscriptionProvider.complimentary, ends_at=NOW + timedelta(days=30))
    granted = evaluate(db_session, site, now=NOW)
    assert (granted.entitled, granted.reason, granted.complimentary) == (True, "complimentary", True)
    assert evaluate(db_session, site, now=NOW + timedelta(days=31)).entitled is False


def test_projects_are_entitled_independently(db_session):
    a, b, c = _site(db_session, "a.example"), _site(db_session, "b.example"), _site(db_session, "c.example")
    org_id = a.organization_id
    b.organization_id = c.organization_id = org_id
    _sub(db_session, a, SubscriptionStatus.active)
    _sub(db_session, b, SubscriptionStatus.past_due, grace_ends_at=NOW - timedelta(days=1))
    assert (evaluate(db_session, a, now=NOW).entitled, evaluate(db_session, b, now=NOW).entitled, evaluate(db_session, c, now=NOW).entitled) \
        == (True, False, False)


def test_an_old_expired_subscription_does_not_hide_the_live_one(db_session):
    site = _site(db_session)
    _sub(db_session, site, SubscriptionStatus.expired)
    _sub(db_session, site, SubscriptionStatus.active)
    assert evaluate(db_session, site, now=NOW).reason == "active"


@pytest.mark.parametrize("mode,raises", [("off", False), ("log", False), ("enforce", True)])
def test_enforcement_modes(db_session, monkeypatch, mode, raises):
    monkeypatch.setattr(get_settings(), "billing_enforcement", mode)
    site = _site(db_session)  # no subscription
    if raises:
        with pytest.raises(EntitlementRequired) as exc:
            check(db_session, site, "crawl")
        assert exc.value.entitlement.reason == "no_subscription" and exc.value.feature == "crawl"
        assert allowed(db_session, site, "crawl") is False
    else:
        assert check(db_session, site, "crawl") is not None
        assert allowed(db_session, site, "crawl") is True


def test_an_entitled_project_passes_in_enforce_mode(db_session, monkeypatch):
    monkeypatch.setattr(get_settings(), "billing_enforcement", "enforce")
    site = _site(db_session)
    _sub(db_session, site, SubscriptionStatus.active)
    assert check(db_session, site, "crawl").entitled is True


def test_an_unknown_mode_never_blocks(monkeypatch):
    monkeypatch.setattr(get_settings(), "billing_enforcement", "banana")
    assert entitlement.enforcement_mode() == "off"


def test_the_default_mode_is_off_so_existing_projects_keep_working():
    assert get_settings().billing_enforcement == "off"
