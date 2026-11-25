"""Super Admin dashboard: numbers are checked against values worked out by hand from the seed data below,
never against the code under test."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.models.audit_event import AuditEvent
from app.models.billing import (
    BillingEvent, BillingEventStatus, BillingInterval, Payment, PaymentStatus, ProjectReplacement, Subscription,
    SubscriptionProvider, SubscriptionStatus, TrialHistory,
)
from app.models.user import User, UserStatus
from app.models.website import Website, WebsiteStatus
from tests.billing_helpers import make_website, register

ADMIN = "qaqadeer@gmail.com"
NOW = datetime.now(timezone.utc)


@pytest.fixture
def admin(client, db_session):
    headers, org = register(client, ADMIN)
    user = db_session.query(User).filter(User.email == ADMIN).one()
    user.email_verified_at = NOW
    db_session.commit()
    return headers, org, user


def _sub(db, org, host, *, status, interval=BillingInterval.month, price=1500, provider=SubscriptionProvider.lemonsqueezy, user=None, **kw):
    site = make_website(db, org, host)
    sub = Subscription(organization_id=uuid.UUID(org), website_id=site.id, user_id=user.id if user else None, provider=provider, status=status,
                       billing_interval=interval, price_cents=price, currency="USD", provider_subscription_id=None if provider == SubscriptionProvider.complimentary else f"ls-{host}", **kw)
    db.add(sub)
    db.commit()
    return site, sub


def _pay(db, sub, key, amount, status=PaymentStatus.paid, reason="initial", interval="month", test=False, refunded=0, paid_at=NOW):
    p = Payment(subscription_id=sub.id, organization_id=sub.organization_id, website_id=sub.website_id, provider=SubscriptionProvider.lemonsqueezy,
                provider_payment_key=f"invoice:{key}", amount_cents=amount, currency="USD", status=status, billing_reason=reason, billing_interval=interval,
                test_mode=test, refunded_cents=refunded, paid_at=paid_at if status != PaymentStatus.failed else None,
                refunded_at=paid_at if refunded else None)
    db.add(p)
    db.commit()
    return p


@pytest.fixture
def seeded(client, db_session, admin):
    headers, org, user = admin
    _, a = _sub(db_session, org, "a.example", status=SubscriptionStatus.active, user=user)
    _, b = _sub(db_session, org, "b.example", status=SubscriptionStatus.active, interval=BillingInterval.year, price=15000)
    _, c = _sub(db_session, org, "c.example", status=SubscriptionStatus.past_due)
    _, d = _sub(db_session, org, "d.example", status=SubscriptionStatus.trialing, interval=BillingInterval.year, price=15000)
    _, e = _sub(db_session, org, "e.example", status=SubscriptionStatus.active, price=0, provider=SubscriptionProvider.complimentary)
    _, f = _sub(db_session, org, "f.example", status=SubscriptionStatus.cancelled, cancelled_at=NOW)
    _pay(db_session, a, "1", 1500)
    _pay(db_session, b, "2", 15000, interval="year")
    _pay(db_session, a, "3", 1500, reason="renewal")
    _pay(db_session, c, "4", 1500, status=PaymentStatus.refunded, reason="renewal", refunded=1500)
    _pay(db_session, c, "5", 1500, status=PaymentStatus.failed, reason="renewal")
    _pay(db_session, a, "6", 9999, test=True)
    for i, outcome in enumerate(["converted", "converted", "cancelled", "active"]):
        site = make_website(db_session, org, f"t{i}.example")
        db_session.add(TrialHistory(website_id=site.id, organization_id=uuid.UUID(org), started_at=NOW, outcome=outcome))
    db_session.commit()
    return headers


def test_overview_matches_hand_computed_values(client, seeded):
    body = client.get("/api/v1/admin/overview?range=30d", headers=seeded).json()
    rev = body["revenue"]
    assert rev["gross_collected_cents"] == {"USD": 19500}
    assert rev["refunds_cents"] == {"USD": 1500}
    assert rev["net_cents"] == {"USD": 18000}
    assert rev["new_subscription_revenue_cents"] == {"USD": 16500}
    assert rev["by_interval_cents"] == {"month": {"USD": 4500}, "year": {"USD": 15000}}
    assert rev["failed_payments"] == {"count": 1, "amount_cents": {"USD": 1500}}
    # MRR: monthly active 1500 + annual active 15000/12=1250 + past_due 1500; trial, complimentary, cancelled excluded
    assert rev["recurring"]["mrr_cents"] == {"USD": 4250}
    assert rev["recurring"]["arr_cents"] == {"USD": 51000}
    assert rev["recurring"]["past_due_mrr_cents"] == {"USD": 1500}
    assert rev["recurring"]["paying_subscriptions"] == 3
    assert body["subscriptions"]["by_status"] == {"active": 3, "past_due": 1, "trialing": 1, "cancelled": 1}
    assert body["subscriptions"]["complimentary"] == 1
    assert body["trials"]["started"] == 4 and body["trials"]["finished"] == 3
    assert body["trials"]["conversion_rate"] == pytest.approx(2 / 3, abs=1e-3)
    # 6 projects hold a live subscription (a-f), 4 only have trial rows
    assert body["projects"] == {"total": 10, "subscribed": 6, "unsubscribed": 4, "suspended": 0}


def test_cash_is_never_added_to_recurring_and_test_payments_are_excluded_by_default(client, seeded):
    live = client.get("/api/v1/admin/revenue?range=30d", headers=seeded).json()
    assert live["gross_collected_cents"] == {"USD": 19500}
    with_test = client.get("/api/v1/admin/revenue?range=30d&include_test=true", headers=seeded).json()
    assert with_test["gross_collected_cents"] == {"USD": 19500 + 9999}
    assert with_test["recurring"]["mrr_cents"] == live["recurring"]["mrr_cents"]  # unaffected by payments


def test_currencies_are_never_mixed(client, db_session, seeded):
    sub = db_session.query(Subscription).filter(Subscription.provider_subscription_id == "ls-a.example").one()
    p = Payment(subscription_id=sub.id, provider=SubscriptionProvider.lemonsqueezy, provider_payment_key="invoice:eur", amount_cents=900,
                currency="EUR", status=PaymentStatus.paid, billing_reason="renewal", billing_interval="month", paid_at=NOW)
    db_session.add(p)
    db_session.commit()
    gross = client.get("/api/v1/admin/revenue?range=30d", headers=seeded).json()["gross_collected_cents"]
    assert gross == {"USD": 19500, "EUR": 900}


def test_date_ranges_filter_payments(client, db_session, seeded):
    sub = db_session.query(Subscription).filter(Subscription.provider_subscription_id == "ls-a.example").one()
    _pay(db_session, sub, "old", 4000, reason="renewal", paid_at=NOW - timedelta(days=45))
    in30 = client.get("/api/v1/admin/revenue?range=30d", headers=seeded).json()["gross_collected_cents"]
    in90 = client.get("/api/v1/admin/revenue?range=90d", headers=seeded).json()["gross_collected_cents"]
    today = client.get("/api/v1/admin/revenue?range=today", headers=seeded).json()["gross_collected_cents"]
    assert in30 == {"USD": 19500} and in90 == {"USD": 23500} and today == {"USD": 19500}
    day = (NOW - timedelta(days=45)).date().isoformat()
    custom = client.get(f"/api/v1/admin/revenue?range=custom&start={day}&end={day}", headers=seeded).json()
    assert custom["gross_collected_cents"] == {"USD": 4000}
    assert len(custom["series"]) == 1


@pytest.mark.parametrize("query", ["range=bogus", "range=custom", "range=custom&start=2026-02-02&end=2026-01-01"])
def test_bad_ranges_are_rejected_cleanly(client, seeded, query):
    r = client.get(f"/api/v1/admin/overview?{query}", headers=seeded)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "invalid_range"


def test_churn_counts_only_paying_subscriptions(client, db_session, seeded):
    sub = db_session.query(Subscription).filter(Subscription.provider_subscription_id == "ls-f.example").one()
    sub.created_at = NOW - timedelta(days=60)
    sub.cancelled_at = NOW - timedelta(days=1)
    db_session.commit()
    _pay(db_session, sub, "f1", 1500, paid_at=NOW - timedelta(days=50))
    churn = client.get("/api/v1/admin/revenue?range=30d", headers=seeded).json()["churn"]
    # base at the start of the range: only f is a paying subscription older than the range (a/b/c were created now)
    assert churn == {"cancelled": 1, "base": 1, "rate": 1.0}


def test_trial_analytics_and_replacement_analytics(client, db_session, seeded):
    sub = db_session.query(Subscription).filter(Subscription.provider_subscription_id == "ls-a.example").one()
    db_session.add_all([ProjectReplacement(subscription_id=sub.id, sequence=1, admin_override=False),
                        ProjectReplacement(subscription_id=sub.id, sequence=2, admin_override=True, reason="support")])
    sub.replacements_used, sub.replacement_limit = 2, 2
    db_session.commit()
    trials = client.get("/api/v1/admin/trials", headers=seeded).json()
    assert (trials["started"], trials["converted"], trials["cancelled"], trials["active"]) == (4, 2, 1, 1)
    rep = client.get("/api/v1/admin/replacements", headers=seeded).json()
    assert rep["summary"]["total"] == 2 and rep["summary"]["admin_overrides"] == 1
    assert rep["summary"]["subscriptions_with_exception_granted"] == 1
    assert len(rep["items"]) == 2


def test_lists_search_filter_paginate_and_sort(client, seeded):
    page1 = client.get("/api/v1/admin/subscriptions?page_size=2&sort=price&dir=desc", headers=seeded).json()
    assert page1["total"] == 6 and page1["pages"] == 3 and len(page1["items"]) == 2
    assert [i["price_cents"] for i in page1["items"]] == [15000, 15000]
    active = client.get("/api/v1/admin/subscriptions?status=active&interval=year", headers=seeded).json()
    assert [i["hostname"] for i in active["items"]] == ["b.example"]
    found = client.get("/api/v1/admin/projects?q=c.exam", headers=seeded).json()
    assert [i["hostname"] for i in found["items"]] == ["c.example"]
    assert found["items"][0]["subscription_status"] == "past_due"
    unsub = client.get("/api/v1/admin/projects?subscribed=false", headers=seeded).json()
    assert unsub["total"] == 4
    assert client.get("/api/v1/admin/subscriptions?status=nope", headers=seeded).status_code == 422
    assert client.get("/api/v1/admin/payments?status=failed", headers=seeded).json()["total"] == 1
    assert client.get("/api/v1/admin/payments", headers=seeded).json()["total"] == 5  # test-mode payment hidden


def test_user_suspend_requires_reason_and_confirmation_and_is_audited(client, db_session, seeded):
    other_h, _ = register(client, "customer@example.com")
    uid = db_session.query(User).filter(User.email == "customer@example.com").one().id
    url = f"/api/v1/admin/users/{uid}/suspend"
    assert client.post(url, json={"reason": "", "confirm": True}, headers=seeded).json()["detail"]["code"] == "reason_required"
    assert client.post(url, json={"reason": "abuse", "confirm": False}, headers=seeded).json()["detail"]["code"] == "confirmation_required"
    assert client.get("/api/v1/me", headers=other_h).status_code == 200
    assert client.post(url, json={"reason": "abuse report", "confirm": True}, headers=seeded).json()["status"] == "disabled"
    assert client.get("/api/v1/me", headers=other_h).status_code in (401, 403)  # suspended users are locked out at once
    db_session.expire_all()
    event = db_session.query(AuditEvent).filter(AuditEvent.action == "admin.user.suspend").one()
    assert event.metadata_json["reason"] == "abuse report" and event.metadata_json["before"] == {"status": "active"}
    # data is kept, and reactivation works
    assert client.post(f"/api/v1/admin/users/{uid}/reactivate", json={"reason": "resolved", "confirm": True}, headers=seeded).json()["status"] == "active"
    assert client.get("/api/v1/me", headers=other_h).status_code == 200


def test_admin_cannot_suspend_self(client, seeded, admin):
    r = client.post(f"/api/v1/admin/users/{admin[2].id}/suspend", json={"reason": "x", "confirm": True}, headers=seeded)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "cannot_suspend_self"


def test_project_suspend_keeps_data_and_is_reversible(client, db_session, seeded):
    site = db_session.query(Website).filter(Website.hostname == "a.example").one()
    r = client.post(f"/api/v1/admin/projects/{site.id}/suspend", json={"reason": "chargeback", "confirm": True}, headers=seeded)
    assert r.status_code == 200 and r.json()["status"] == "paused"
    db_session.expire_all()
    assert db_session.get(Website, site.id) is not None
    assert client.post(f"/api/v1/admin/projects/{site.id}/reactivate", json={"reason": "ok", "confirm": True}, headers=seeded).json()["status"] == "active"
    assert not any(route.methods and "DELETE" in route.methods and "/projects" in route.path for route in __import__("app.api.v1.endpoints.admin", fromlist=["router"]).router.routes)


def test_complimentary_grant_is_not_revenue(client, db_session, seeded):
    site = db_session.query(Website).filter(Website.hostname == "t0.example").one()
    url = f"/api/v1/admin/projects/{site.id}/complimentary"
    assert client.post(url, json={"reason": "own site", "confirm": False}, headers=seeded).status_code == 422
    r = client.post(url, json={"reason": "own site", "confirm": True, "days": 30}, headers=seeded)
    assert r.status_code == 200 and r.json()["provider"] == "complimentary" and r.json()["price_cents"] == 0
    assert client.post(url, json={"reason": "again", "confirm": True}, headers=seeded).status_code == 409  # one live subscription per project
    rev = client.get("/api/v1/admin/revenue", headers=seeded).json()["recurring"]
    assert rev["mrr_cents"] == {"USD": 4250}


def test_extend_trial_only_for_locally_managed_access(client, db_session, seeded):
    lemon = db_session.query(Subscription).filter(Subscription.provider_subscription_id == "ls-d.example").one()
    r = client.post(f"/api/v1/admin/subscriptions/{lemon.id}/extend-trial", json={"reason": "r", "confirm": True, "days": 7}, headers=seeded)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "provider_managed"
    comp = db_session.query(Subscription).filter(Subscription.provider == SubscriptionProvider.complimentary).one()
    comp.ends_at = NOW + timedelta(days=2)
    db_session.commit()
    r = client.post(f"/api/v1/admin/subscriptions/{comp.id}/extend-trial", json={"reason": "support", "confirm": True, "days": 7}, headers=seeded)
    assert r.status_code == 200
    db_session.expire_all()
    assert abs((db_session.get(Subscription, comp.id).ends_at - (NOW + timedelta(days=9))).total_seconds()) < 5
    assert client.post(f"/api/v1/admin/subscriptions/{comp.id}/extend-trial", json={"reason": "r", "confirm": True, "days": 0}, headers=seeded).status_code == 422


def test_replacement_exception_adds_exactly_one_and_is_audited(client, db_session, seeded):
    sub = db_session.query(Subscription).filter(Subscription.provider_subscription_id == "ls-a.example").one()
    url = f"/api/v1/admin/subscriptions/{sub.id}/replacement-exception"
    assert client.post(url, json={"reason": "", "confirm": True}, headers=seeded).status_code == 422
    assert client.post(url, json={"reason": "migrated domain", "confirm": True}, headers=seeded).json()["replacement_limit"] == 2
    detail = client.get(f"/api/v1/admin/subscriptions/{sub.id}", headers=seeded).json()
    assert detail["provider_subscription_id"] == "ls-a.example" and len(detail["payments"]) == 3  # payments 1, 3 and the test-mode one (the detail view shows everything, flagged)
    assert db_session.query(AuditEvent).filter(AuditEvent.action == "billing.replacement_exception_granted").count() == 1


def test_webhook_history_hides_payloads_and_retry_needs_a_failed_event(client, db_session, seeded):
    ev = BillingEvent(provider="lemonsqueezy", event_key="k" * 64, event_name="subscription_updated", status=BillingEventStatus.processed,
                      payload_json={"customer_email": "private@example.com"})
    db_session.add(ev)
    db_session.commit()
    listing = client.get("/api/v1/admin/webhooks", headers=seeded)
    assert "private@example.com" not in listing.text and "payload" not in listing.text
    assert listing.json()["counts"]["processed"] == 1
    r = client.post(f"/api/v1/admin/webhooks/{ev.id}/retry", json={"reason": "r", "confirm": True}, headers=seeded)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "not_failed"


def test_settings_validate_confirm_audit_and_take_effect(client, db_session, seeded, admin, monkeypatch):
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "billing_provider", "lemonsqueezy")  # the legacy price config is what this setting drives
    listing = client.get("/api/v1/admin/settings", headers=seeded).json()
    prices = next(i for i in listing["items"] if i["key"] == "price_monthly_cents")
    assert prices["value"] == 1500 and prices["source"] == "environment"
    url = "/api/v1/admin/settings/price_monthly_cents"
    assert client.put(url, json={"value": 1900, "reason": "test", "confirm": False}, headers=seeded).json()["detail"]["code"] == "confirmation_required"
    assert client.put(url, json={"value": -5, "reason": "test", "confirm": True}, headers=seeded).json()["detail"]["code"] == "invalid_value"
    assert client.put(url, json={"value": "1900", "reason": "test", "confirm": True}, headers=seeded).status_code == 422
    assert client.put("/api/v1/admin/settings/super_admin_email", json={"value": "x@y.z", "reason": "t", "confirm": True}, headers=seeded).status_code == 404
    assert client.put(url, json={"value": 1900, "reason": "price test", "confirm": True}, headers=seeded).json() == {"key": "price_monthly_cents", "value": 1900, "previous": 1500}
    plans = client.get("/api/v1/billing/plans", headers=seeded).json()
    assert [p["price_cents"] for p in plans["plans"] if p["interval"] == "month"] == [1900]
    # existing subscriptions keep the price they were bought at
    assert db_session.query(Subscription).filter(Subscription.provider_subscription_id == "ls-a.example").one().price_cents == 1500
    audit = db_session.query(AuditEvent).filter(AuditEvent.action == "admin.setting.update").one()
    assert audit.metadata_json["before"] == {"value": 1500} and audit.metadata_json["after"] == {"value": 1900}
    r = client.request("DELETE", url, json={"reason": "revert", "confirm": True}, headers=seeded)
    assert r.json()["value"] == 1500
    assert [p["price_cents"] for p in client.get("/api/v1/billing/plans", headers=seeded).json()["plans"] if p["interval"] == "month"] == [1500]


def test_audit_log_is_read_only_and_shows_reason_and_states(client, db_session, seeded, admin):
    site = db_session.query(Website).filter(Website.hostname == "a.example").one()
    client.post(f"/api/v1/admin/projects/{site.id}/suspend", json={"reason": "fraud review", "confirm": True}, headers=seeded)
    items = client.get("/api/v1/admin/audit-logs?action=admin.project.suspend", headers=seeded).json()["items"]
    assert len(items) == 1
    entry = items[0]
    assert (entry["admin"], entry["reason"], entry["before"], entry["after"]) == (ADMIN, "fraud review", {"status": "active"}, {"status": "paused"})
    from app.api.v1.endpoints.admin import router
    for route in router.routes:
        if "audit" in route.path:
            assert route.methods == {"GET"}


def test_ai_usage_reports_estimated_cost_and_flags_days_over_threshold(client, db_session, seeded):
    from app.models.agent_run import AgentRun, AgentRunStatus, AgentType
    site = db_session.query(Website).filter(Website.hostname == "a.example").one()
    for cost, status in [(30.0, AgentRunStatus.succeeded), (25.0, AgentRunStatus.succeeded), (1.5, AgentRunStatus.failed)]:
        db_session.add(AgentRun(website_id=site.id, agent_type=list(AgentType)[0], model="gpt-test", status=status, input_tokens=1000, output_tokens=500,
                                estimated_cost=cost, started_at=NOW))
    db_session.commit()
    resp = client.get("/api/v1/admin/ai-costs?range=7d", headers=seeded)
    body = resp.json()
    assert body["cost_basis"] == "estimated"
    assert (body["runs"], body["failed_runs"], body["input_tokens"], body["output_tokens"]) == (3, 1, 3000, 1500)
    assert body["estimated_cost_usd"] == 56.5
    assert body["by_project"][0]["estimated_cost_usd"] == 56.5
    assert body["daily"] == [{"date": NOW.date().isoformat(), "estimated_cost_usd": 56.5, "over_threshold": True}]  # default threshold 50


def test_health_reports_real_failures_and_never_leaks_secrets(client, db_session, seeded):
    db_session.add(BillingEvent(provider="lemonsqueezy", event_key="f" * 64, event_name="subscription_updated", status=BillingEventStatus.failed, error="boom"))
    db_session.commit()
    body = client.get("/api/v1/admin/health", headers=seeded).json()
    checks = {c["name"]: c for c in body["checks"]}
    assert checks["database"]["state"] == "ok" and checks["api"]["state"] == "ok"
    assert checks["billing_webhooks"]["failed"] == 1 and checks["billing_webhooks"]["state"] == "warning"
    assert checks["payment_sync"]["failed_7d"] == 1
    assert body["overall"] in ("warning", "error")
    text = client.get("/api/v1/admin/health", headers=seeded).text.lower()
    for forbidden in ("postgresql://", "redis://", "api_key", "secret", "password"):
        assert forbidden not in text


def test_no_admin_endpoint_is_reachable_by_a_regular_or_anonymous_user(client, seeded):
    other, _ = register(client, "regular@example.com")
    for path in ["overview", "users", "projects", "subscriptions", "payments", "revenue", "trials", "replacements", "ai-costs", "webhooks", "health", "audit-logs", "settings"]:
        assert client.get(f"/api/v1/admin/{path}").status_code in (401, 403), path
        assert client.get(f"/api/v1/admin/{path}", headers=other).status_code == 403, path
