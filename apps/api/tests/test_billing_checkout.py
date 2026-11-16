import uuid

import pytest

from app.billing import checkout as checkout_module
from app.billing.provider import ProviderError
from app.models.billing import (
    BillingInterval, CheckoutSession, CheckoutStatus, Subscription, SubscriptionProvider, SubscriptionStatus, TrialHistory,
)
from datetime import datetime, timezone
from tests.billing_helpers import FakeProvider, billing_settings, make_website, register  # noqa: F401


def _url(org, site):
    return f"/api/v1/organizations/{org}/websites/{site.id}/billing/checkout"


@pytest.fixture
def provider(monkeypatch):
    fake = FakeProvider()
    monkeypatch.setattr(checkout_module, "get_provider", lambda: fake)
    return fake


def test_plans_endpoint_shows_the_approved_prices(client, billing_settings):
    headers, _ = register(client, "plans@example.com")
    body = client.get("/api/v1/billing/plans", headers=headers).json()
    assert {p["interval"]: (p["price_cents"], p["trial_days"], p["monthly_equivalent_cents"]) for p in body["plans"]} == {
        "month": (1500, 7, 1500), "year": (15000, 7, 1250),
    }
    assert body["annual_saving_cents"] == 3000
    assert client.get("/api/v1/billing/plans").status_code in (401, 403)


@pytest.mark.parametrize("interval,variant,price", [("month", "111", 1500), ("year", "222", 15000)])
def test_checkout_uses_server_side_variant_and_price_and_tells_the_buyer_about_the_trial(
    client, db_session, billing_settings, provider, interval, variant, price
):
    headers, org = register(client, f"co-{interval}@example.com")
    site = make_website(db_session, org)

    r = client.post(_url(org, site), json={"interval": interval}, headers=headers)

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["checkout_url"].startswith("https://store.example/checkout/")
    assert (body["price_cents"], body["currency"], body["with_trial"], body["trial_days"]) == (price, "USD", True, 7)
    assert body["first_charge_at"] is not None
    call = provider.calls[0]
    assert call["variant_id"] == variant
    custom = call["custom_data"]
    assert custom["project_id"] == str(site.id) and custom["organization_id"] == org and custom["interval"] == interval
    assert custom["reference"]
    assert "price" not in str(call).lower()  # the price is the variant's, never sent from our side


def test_the_browser_cannot_choose_the_price_the_variant_or_another_project(client, db_session, billing_settings, provider):
    headers, org = register(client, "tamper@example.com")
    site = make_website(db_session, org)
    r = client.post(_url(org, site), json={"interval": "month", "price_cents": 1, "variant_id": "999",
                                           "website_id": str(uuid.uuid4())}, headers=headers)
    assert r.status_code == 200
    assert provider.calls[0]["variant_id"] == "111"
    assert client.post(_url(org, site), json={"interval": "weekly"}, headers=headers).status_code == 422


def test_only_org_admins_can_start_a_checkout_and_other_tenants_cannot_touch_the_project(client, db_session, billing_settings, provider):
    headers, org = register(client, "owner@example.com")
    other_headers, other_org = register(client, "intruder@example.com")
    site = make_website(db_session, org)

    assert client.post(_url(org, site), json={"interval": "month"}, headers=other_headers).status_code == 403
    # their own org id with someone else's project id: not found
    assert client.post(_url(other_org, site), json={"interval": "month"}, headers=other_headers).status_code == 404
    assert provider.calls == []


def test_a_second_click_returns_the_same_checkout_and_asks_the_provider_once(client, db_session, billing_settings, provider):
    headers, org = register(client, "dbl@example.com")
    site = make_website(db_session, org)
    first = client.post(_url(org, site), json={"interval": "month"}, headers=headers).json()
    second = client.post(_url(org, site), json={"interval": "month"}, headers=headers).json()
    assert first["checkout_url"] == second["checkout_url"]
    assert len(provider.calls) == 1
    assert db_session.query(CheckoutSession).filter(CheckoutSession.website_id == site.id).count() == 1


def test_switching_plan_before_paying_replaces_the_pending_checkout(client, db_session, billing_settings, provider):
    headers, org = register(client, "switch@example.com")
    site = make_website(db_session, org)
    client.post(_url(org, site), json={"interval": "month"}, headers=headers)
    client.post(_url(org, site), json={"interval": "year"}, headers=headers)
    sessions = db_session.query(CheckoutSession).filter(CheckoutSession.website_id == site.id).all()
    assert sorted(s.status.value for s in sessions) == ["expired", "pending"]
    assert provider.calls[1]["variant_id"] == "222"


def test_an_already_subscribed_project_cannot_check_out_again(client, db_session, billing_settings, provider):
    headers, org = register(client, "again@example.com")
    site = make_website(db_session, org)
    db_session.add(Subscription(organization_id=site.organization_id, website_id=site.id, provider=SubscriptionProvider.lemonsqueezy,
                                provider_subscription_id="77", status=SubscriptionStatus.cancelled,  # cancelled but still live
                                billing_interval=BillingInterval.month, price_cents=1500))
    db_session.commit()
    r = client.post(_url(org, site), json={"interval": "month"}, headers=headers)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "already_subscribed"
    assert provider.calls == []


def test_a_project_that_already_had_its_trial_gets_the_no_trial_variant(client, db_session, billing_settings, provider):
    headers, org = register(client, "retrial@example.com")
    site = make_website(db_session, org)
    db_session.add(TrialHistory(website_id=site.id, organization_id=site.organization_id, started_at=datetime.now(timezone.utc), outcome="expired"))
    db_session.commit()

    body = client.post(_url(org, site), json={"interval": "year"}, headers=headers).json()

    assert provider.calls[0]["variant_id"] == "224"
    assert body["with_trial"] is False and body["trial_days"] == 0 and body["first_charge_at"] is None


def test_without_a_no_trial_variant_a_second_trial_is_refused_not_granted(client, db_session, billing_settings, provider, monkeypatch):
    monkeypatch.setattr(billing_settings, "lemonsqueezy_variant_monthly_no_trial", None)
    headers, org = register(client, "notrial@example.com")
    site = make_website(db_session, org)
    db_session.add(TrialHistory(website_id=site.id, organization_id=site.organization_id, started_at=datetime.now(timezone.utc), outcome="expired"))
    db_session.commit()
    r = client.post(_url(org, site), json={"interval": "month"}, headers=headers)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "trial_used"
    assert provider.calls == []


def test_unconfigured_billing_says_so(client, db_session, billing_settings, provider, monkeypatch):
    monkeypatch.setattr(billing_settings, "lemonsqueezy_variant_monthly", None)
    headers, org = register(client, "unconf@example.com")
    site = make_website(db_session, org)
    r = client.post(_url(org, site), json={"interval": "month"}, headers=headers)
    assert r.status_code == 503 and r.json()["detail"]["code"] == "not_configured"


def test_a_provider_failure_is_reported_and_does_not_block_a_retry(client, db_session, billing_settings, monkeypatch):
    fake = FakeProvider(fail=ProviderError("boom"))
    monkeypatch.setattr(checkout_module, "get_provider", lambda: fake)
    headers, org = register(client, "fail@example.com")
    site = make_website(db_session, org)

    r = client.post(_url(org, site), json={"interval": "month"}, headers=headers)
    assert r.status_code == 502 and r.json()["detail"]["code"] == "provider_error"
    assert db_session.query(CheckoutSession).filter(CheckoutSession.website_id == site.id).one().status == CheckoutStatus.failed

    fake.fail = None
    assert client.post(_url(org, site), json={"interval": "month"}, headers=headers).status_code == 200


# --- one trial per DOMAIN, and no duplicate projects ---------------------------------------------

def _trial_row(db_session, site, org_id):
    from app.core.domains import domain_key
    from app.models.billing import TrialHistory
    db_session.add(TrialHistory(website_id=site.id, organization_id=uuid.UUID(org_id), started_at=datetime.now(timezone.utc), domain_key=domain_key(site.hostname)))
    db_session.commit()


def test_a_readded_or_other_account_copy_of_the_same_domain_gets_no_second_trial(client, db_session):
    from app.billing.checkout import trial_already_used
    from tests.billing_helpers import make_website, register
    _, org1 = register(client, "first@example.com")
    _, org2 = register(client, "second@example.com")
    original = make_website(db_session, org1, "www.Shop.example")
    _trial_row(db_session, original, org1)
    again = make_website(db_session, org1, "shop.example")          # deleted and re-added
    elsewhere = make_website(db_session, org2, "SHOP.example")      # same domain, another account
    other = make_website(db_session, org2, "different.example")
    assert trial_already_used(db_session, original)
    assert trial_already_used(db_session, again)
    assert trial_already_used(db_session, elsewhere)
    assert not trial_already_used(db_session, other)


def test_the_same_site_cannot_be_registered_twice_in_a_workspace(client, db_session, monkeypatch):
    from app.core import url_safety
    from tests.billing_helpers import register
    def fake(url):
        host = url.split("//")[1].split("/")[0].lower()
        return url_safety.SafeUrl(normalized_url=f"https://{host}/", hostname=host, resolved_ip="93.184.216.34", request_url=f"https://{host}/")
    monkeypatch.setattr("app.api.v1.endpoints.websites.validate_public_url", fake)
    headers, org = register(client, "dupes@example.com")
    path = f"/api/v1/organizations/{org}/websites"
    assert client.post(path, json={"url": "https://shop.example", "display_name": "A", "purpose": "owned"}, headers=headers).status_code == 201
    for url in ("https://shop.example", "https://www.shop.example", "https://SHOP.example/"):
        r = client.post(path, json={"url": url, "display_name": "B", "purpose": "owned"}, headers=headers)
        assert r.status_code == 409 and r.json()["detail"]["code"] == "duplicate_project", url
    assert client.post(path, json={"url": "https://another.example", "display_name": "C", "purpose": "owned"}, headers=headers).status_code == 201
