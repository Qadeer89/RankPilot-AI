import uuid
from datetime import datetime, timedelta, timezone

from app.models.billing import (
    BillingInterval, Payment, PaymentStatus, Subscription, SubscriptionProvider, SubscriptionStatus, TrialHistory,
)
from tests.billing_helpers import billing_settings, make_website, register  # noqa: F401

NOW = datetime.now(timezone.utc)


def _sub(site, **kw):
    base = dict(organization_id=site.organization_id, website_id=site.id, provider=SubscriptionProvider.lemonsqueezy,
                provider_subscription_id=uuid.uuid4().hex[:8], status=SubscriptionStatus.active, billing_interval=BillingInterval.month,
                price_cents=1500, customer_portal_url="https://store.example/portal", renews_at=NOW + timedelta(days=20))
    base.update(kw)
    return Subscription(**base)


def test_overview_groups_each_project_with_its_own_subscription(client, db_session, billing_settings):
    headers, org = register(client, "ov@example.com")
    a, b, c = (make_website(db_session, org, f"{n}.example") for n in "abc")
    sub_a = _sub(a)
    sub_b = _sub(b, billing_interval=BillingInterval.year, price_cents=15000, status=SubscriptionStatus.trialing, trial_ends_at=NOW + timedelta(days=3))
    db_session.add_all([sub_a, sub_b])
    db_session.flush()
    db_session.add(Payment(subscription_id=sub_a.id, organization_id=a.organization_id, website_id=a.id, provider=SubscriptionProvider.lemonsqueezy,
                           provider_payment_key="invoice:1", amount_cents=1500, status=PaymentStatus.paid, paid_at=NOW))
    db_session.commit()

    body = client.get(f"/api/v1/organizations/{org}/billing/overview", headers=headers).json()

    by_host = {p["hostname"]: p for p in body["projects"]}
    assert (by_host["a.example"]["subscription"]["interval"], by_host["a.example"]["subscription"]["price_cents"]) == ("month", 1500)
    assert (by_host["b.example"]["subscription"]["interval"], by_host["b.example"]["subscription"]["status"]) == ("year", "trialing")
    assert by_host["c.example"]["subscription"] is None and by_host["c.example"]["can_start_plan"] is True
    assert by_host["c.example"]["entitlement"]["reason"] == "no_subscription"
    assert [pay["amount_cents"] for pay in by_host["a.example"]["payments"]] == [1500] and by_host["b.example"]["payments"] == []
    assert by_host["a.example"]["subscription"]["customer_portal_url"] == "https://store.example/portal"
    assert by_host["a.example"]["subscription"]["replacements_remaining"] == 1
    assert body["enforcement"] == "off" and body["annual_saving_cents"] == 3000
    assert {p["interval"]: p["price_cents"] for p in body["plans"]} == {"month": 1500, "year": 15000}


def test_a_scheduled_cancellation_and_a_used_trial_are_visible(client, db_session, billing_settings):
    headers, org = register(client, "ov2@example.com")
    site = make_website(db_session, org)
    db_session.add(_sub(site, status=SubscriptionStatus.cancelled, ends_at=NOW + timedelta(days=9)))
    db_session.add(TrialHistory(website_id=site.id, organization_id=site.organization_id, started_at=NOW, outcome="cancelled"))
    db_session.commit()
    project = client.get(f"/api/v1/organizations/{org}/billing/overview", headers=headers).json()["projects"][0]
    assert project["subscription"]["cancellation_scheduled"] is True
    assert project["entitlement"]["entitled"] is True and project["entitlement"]["reason"] == "cancelled_until_end"
    assert project["can_start_plan"] is False


def test_a_project_that_used_its_trial_is_told_so(client, db_session, billing_settings):
    headers, org = register(client, "ov3@example.com")
    site = make_website(db_session, org)
    db_session.add(TrialHistory(website_id=site.id, organization_id=site.organization_id, started_at=NOW, outcome="expired"))
    db_session.commit()
    project = client.get(f"/api/v1/organizations/{org}/billing/overview", headers=headers).json()["projects"][0]
    assert project["trial_available"] is False and project["can_start_plan"] is True


def test_a_complimentary_grant_is_shown_as_free(client, db_session, billing_settings):
    headers, org = register(client, "ov4@example.com")
    site = make_website(db_session, org)
    db_session.add(Subscription(organization_id=site.organization_id, website_id=site.id, provider=SubscriptionProvider.complimentary,
                                status=SubscriptionStatus.active, billing_interval=BillingInterval.month, price_cents=1500))
    db_session.commit()
    sub = client.get(f"/api/v1/organizations/{org}/billing/overview", headers=headers).json()["projects"][0]["subscription"]
    assert (sub["complimentary"], sub["price_cents"]) == (True, 0)


def test_only_workspace_admins_see_billing_and_tenants_are_isolated(client, db_session, billing_settings):
    headers, org = register(client, "ov5@example.com")
    other_headers, other_org = register(client, "ov5-other@example.com")
    site = make_website(db_session, org, "secret.example")
    db_session.add(_sub(site))
    db_session.commit()
    assert client.get(f"/api/v1/organizations/{org}/billing/overview", headers=other_headers).status_code == 403
    mine = client.get(f"/api/v1/organizations/{other_org}/billing/overview", headers=other_headers).json()
    assert "secret.example" not in str(mine)
    assert client.get(f"/api/v1/organizations/{org}/billing/overview").status_code in (401, 403)
