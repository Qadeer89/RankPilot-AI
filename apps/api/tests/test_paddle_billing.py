"""Paddle Billing: signature, webhook state machine, checkout, catalogue and entitlement tests.
Webhook bodies follow Paddle's documented notification shape and are signed with the REAL h1 scheme; Paddle's HTTP API is faked.
That is evidence for our handling, not proof that a real Paddle sandbox works (see docs/PADDLE_BILLING.md)."""

import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.billing import catalog, checkout as checkout_module, features
from app.billing.paddle import parse_signature_header, sign_for_tests, verify_paddle_signature
from app.billing.provider import CheckoutResult, ProviderError
from app.config import get_settings
from app.models.billing import (
    BillingEvent, BillingEventStatus, BillingPlan, CheckoutSession, CheckoutStatus, Payment, PaymentStatus, Subscription,
    SubscriptionProvider, SubscriptionStatus, BillingInterval,
)
from app.models.user import User
from app.models.website import Website
from tests.billing_helpers import make_website, register

SECRET = "pdl_ntfset_test_secret"
URL = "/api/v1/billing/webhooks/paddle"
T0 = datetime(2026, 11, 16, 10, 0, 0, tzinfo=timezone.utc)


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000000Z")


@pytest.fixture
def paddle_settings(monkeypatch):
    s = get_settings()
    for k, v in {"billing_provider": "paddle", "paddle_env": "sandbox", "paddle_api_key": "k", "paddle_webhook_secret": SECRET,
                 "paddle_signature_tolerance_seconds": 300, "billing_enforcement": "off"}.items():
        monkeypatch.setattr(s, k, v, raising=False)
    return s


def make_plan(db, code="pro_m", *, amount=2000, interval=BillingInterval.month, approved=False, test=True, trial=7, price="pri_trial",
              price_nt="pri_notrial", active=True, public=True, **kw):
    plan = BillingPlan(code=code, name=code, billing_interval=interval, amount_cents=amount, currency="USD", paddle_price_id=price,
                       paddle_price_id_no_trial=price_nt, trial_days=trial, is_active=active, is_public=public, is_approved=approved,
                       is_test_config=test, **kw)
    db.add(plan)
    db.commit()
    return plan


class FakePaddle:
    def __init__(self, fail=None):
        self.calls, self.fail = [], fail

    def create_checkout(self, **kw):
        self.calls.append(kw)
        if self.fail:
            raise self.fail
        return CheckoutResult(url="https://pay.example/c", provider_checkout_id="txn_01")


@pytest.fixture
def fake(monkeypatch, paddle_settings):
    f = FakePaddle()
    return f


def post(client, body, *, ts=None, secret=SECRET, signature="auto"):
    raw = body if isinstance(body, bytes) else json.dumps(body).encode()
    headers = {} if signature is None else {"Paddle-Signature": sign_for_tests(raw, secret, ts=ts) if signature == "auto" else signature}
    return client.post(URL, content=raw, headers=headers)


def sub_event(session, *, event_id="evt_1", etype="subscription.created", status="trialing", sub_id="sub_01", occurred=T0, price="pri_trial",
              scheduled=None, canceled_at=None):
    return {
        "event_id": event_id, "event_type": etype, "occurred_at": iso(occurred), "notification_id": "ntf_1",
        "data": {
            "id": sub_id, "status": status, "customer_id": "ctm_01", "currency_code": "USD", "started_at": iso(T0), "canceled_at": canceled_at,
            "next_billed_at": iso(T0 + timedelta(days=7)), "scheduled_change": scheduled,
            "custom_data": {"reference": session.reference}, "management_urls": {"update_payment_method": "https://pay.example/pm"},
            "items": [{"price": {"id": price, "unit_price": {"amount": "2000", "currency_code": "USD"}},
                       "trial_dates": {"ends_at": iso(T0 + timedelta(days=7))} if status == "trialing" else None}],
        },
    }


def txn_event(session, *, event_id="evt_t", etype="transaction.completed", txn="txn_01", sub_id="sub_01", total="2000"):
    return {"event_id": event_id, "event_type": etype, "occurred_at": iso(T0),
            "data": {"id": txn, "subscription_id": sub_id, "customer_id": "ctm_01", "currency_code": "USD", "billed_at": iso(T0), "origin": "web",
                     "custom_data": {"reference": session.reference}, "details": {"totals": {"grand_total": total}}}}


@pytest.fixture
def setup(client, db_session, paddle_settings):
    headers, org = register(client, "pd@example.com")
    user = db_session.query(User).filter(User.email == "pd@example.com").one()
    site = make_website(db_session, org)
    plan = make_plan(db_session)
    session = CheckoutSession(organization_id=site.organization_id, user_id=user.id, website_id=site.id, billing_interval=BillingInterval.month,
                              variant_id="pri_trial", expected_price_cents=2000, with_trial=True, reference=uuid.uuid4().hex,
                              status=CheckoutStatus.pending, checkout_url="https://pay.example/c", provider="paddle", plan_id=plan.id,
                              expires_at=datetime.now(timezone.utc) + timedelta(days=1))
    db_session.add(session)
    db_session.commit()
    return headers, org, site, plan, session, user


def the_sub(db):
    return db.query(Subscription).filter(Subscription.provider_subscription_id == "sub_01").one_or_none()


# ---------------------------------------------------------------- signature unit tests

def test_signature_valid_invalid_stale_and_malformed():
    raw = b'{"a":1}'
    now = 1_700_000_000
    good = sign_for_tests(raw, SECRET, ts=now)
    assert verify_paddle_signature(raw, good, SECRET, tolerance_seconds=5, now=now)
    assert not verify_paddle_signature(raw + b" ", good, SECRET, tolerance_seconds=5, now=now)
    assert not verify_paddle_signature(raw, good, "other", tolerance_seconds=5, now=now)
    assert not verify_paddle_signature(raw, good, SECRET, tolerance_seconds=5, now=now + 60)  # replay of an old delivery
    for bad in (None, "", "garbage", "ts=abc;h1=00", "ts=1", "h1=00"):
        assert not verify_paddle_signature(raw, bad, SECRET, tolerance_seconds=5, now=now)
    assert not verify_paddle_signature(raw, good, None, tolerance_seconds=5, now=now)
    assert parse_signature_header("ts=1;h1=a;h1=b")[0] == "1"


# ---------------------------------------------------------------- webhook endpoint

@pytest.mark.parametrize("signature", [None, "", "ts=1;h1=deadbeef"])
def test_bad_signature_changes_nothing(client, db_session, setup, signature):
    *_, session, _ = setup
    r = post(client, sub_event(session), signature=signature)
    assert r.status_code == 401
    assert the_sub(db_session) is None
    assert db_session.query(BillingEvent).filter(BillingEvent.status == BillingEventStatus.rejected).count() == 1


def test_stale_signature_is_rejected(client, db_session, setup):
    *_, session, _ = setup
    assert post(client, sub_event(session), ts=1_600_000_000).status_code == 401
    assert the_sub(db_session) is None


def test_tampered_body_is_rejected(client, db_session, setup):
    *_, session, _ = setup
    raw = json.dumps(sub_event(session)).encode()
    header = sign_for_tests(raw, SECRET)
    assert client.post(URL, content=raw.replace(b"trialing", b"active"), headers={"Paddle-Signature": header}).status_code == 401


def test_no_secret_configured_nothing_verifies(client, setup, monkeypatch):
    *_, session, _ = setup
    monkeypatch.setattr(get_settings(), "paddle_webhook_secret", None)
    assert post(client, sub_event(session)).status_code == 401


def test_subscription_created_trialing_unlocks_only_that_project(client, db_session, setup):
    _, _, site, plan, session, user = setup
    r = post(client, sub_event(session))
    assert r.status_code == 200, r.text
    sub = the_sub(db_session)
    assert (sub.website_id, sub.organization_id, sub.user_id, sub.plan_id) == (site.id, site.organization_id, user.id, plan.id)
    assert sub.provider == SubscriptionProvider.paddle and sub.status == SubscriptionStatus.trialing
    assert sub.price_cents == 2000
    db_session.refresh(session)
    assert session.status == CheckoutStatus.completed


def test_redirect_alone_never_activates(client, db_session, setup):
    headers, org, site, *_ = setup
    r = client.get(f"/api/v1/organizations/{org}/billing/overview?checkout=return&project={site.id}", headers=headers)
    assert the_sub(db_session) is None  # only a verified webhook creates a subscription


def test_duplicate_event_is_processed_once(client, db_session, setup):
    *_, session, _ = setup
    body = sub_event(session)
    assert post(client, body).status_code == 200
    assert post(client, body).json()["status"] == "duplicate"
    assert db_session.query(Subscription).count() == 1
    assert db_session.query(BillingEvent).filter(BillingEvent.event_key == "paddle:evt_1").count() == 1


def test_out_of_order_older_event_does_not_regress(client, db_session, setup):
    *_, session, _ = setup
    assert post(client, sub_event(session, event_id="e1", status="active", occurred=T0 + timedelta(hours=2))).status_code == 200
    assert post(client, sub_event(session, event_id="e0", status="trialing", occurred=T0)).status_code == 200
    assert the_sub(db_session).status == SubscriptionStatus.active


def test_unlinked_subscription_event_is_retried_not_lost(client, db_session, paddle_settings):
    ghost = type("S", (), {"reference": "nope"})()
    r = post(client, sub_event(ghost, sub_id="sub_ghost"))
    assert r.status_code >= 500  # Paddle retries
    ev = db_session.query(BillingEvent).filter(BillingEvent.event_key == "paddle:evt_1").one()
    assert ev.status == BillingEventStatus.failed and ev.attempts == 1


def test_lifecycle_active_past_due_recover_cancel_pause_expire(client, db_session, setup):
    *_, session, _ = setup
    steps = [
        ("active", SubscriptionStatus.active, None), ("past_due", SubscriptionStatus.past_due, None), ("active", SubscriptionStatus.active, None),
        ("paused", SubscriptionStatus.paused, None), ("active", SubscriptionStatus.active, None),
    ]
    for i, (paddle_status, expected, _) in enumerate(steps):
        etype = "subscription.created" if i == 0 else "subscription.updated"
        assert post(client, sub_event(session, event_id=f"e{i}", etype=etype, status=paddle_status, occurred=T0 + timedelta(hours=i))).status_code == 200
        assert the_sub(db_session).status == expected, paddle_status
    # scheduled cancel keeps access until the end of the period
    sched = {"action": "cancel", "effective_at": iso(T0 + timedelta(days=30))}
    post(client, sub_event(session, event_id="ec", etype="subscription.updated", status="active", occurred=T0 + timedelta(hours=10), scheduled=sched))
    sub = the_sub(db_session)
    assert sub.status == SubscriptionStatus.cancelled and sub.ends_at is not None
    # period ends -> canceled -> expired; the project and its data stay
    post(client, sub_event(session, event_id="ex", etype="subscription.canceled", status="canceled", occurred=T0 + timedelta(hours=20), canceled_at=iso(T0 + timedelta(days=30))))
    assert the_sub(db_session).status == SubscriptionStatus.expired


def test_expiry_keeps_customer_data(client, db_session, setup):
    _, _, site, *_, session, _ = setup
    post(client, sub_event(session, status="active"))
    post(client, sub_event(session, event_id="ex", etype="subscription.canceled", status="canceled", occurred=T0 + timedelta(hours=5), canceled_at=iso(T0)))
    assert db_session.get(Website, site.id) is not None and db_session.get(Website, site.id).status.value != "deleted"


def test_transaction_completed_records_payment_once_and_failure_never_unpays(client, db_session, setup):
    *_, session, _ = setup
    post(client, sub_event(session, status="active"))
    post(client, txn_event(session))
    post(client, txn_event(session, event_id="evt_t2"))
    pay = db_session.query(Payment).filter(Payment.provider == SubscriptionProvider.paddle).all()
    assert len(pay) == 1 and pay[0].amount_cents == 2000 and pay[0].status == PaymentStatus.paid and pay[0].subscription_id is not None
    post(client, txn_event(session, event_id="evt_f", etype="transaction.payment_failed"))
    db_session.refresh(pay[0])
    assert pay[0].status == PaymentStatus.paid


def test_refund_adjustment_marks_payment(client, db_session, setup):
    *_, session, _ = setup
    post(client, sub_event(session, status="active"))
    post(client, txn_event(session))
    adj = {"event_id": "evt_a", "event_type": "adjustment.created", "occurred_at": iso(T0 + timedelta(hours=1)),
           "data": {"id": "adj_1", "action": "refund", "status": "approved", "transaction_id": "txn_01", "totals": {"total": "2000"}}}
    assert post(client, adj).status_code == 200
    assert db_session.query(Payment).filter(Payment.provider == SubscriptionProvider.paddle).one().status == PaymentStatus.refunded


def test_unreadable_signed_body_is_ignored_not_crashing(client, db_session, paddle_settings):
    assert post(client, b"not json").status_code == 200


# ---------------------------------------------------------------- checkout

def _checkout(client, org, site, headers, **body):
    return client.post(f"/api/v1/organizations/{org}/websites/{site.id}/billing/checkout", json={"interval": "month", **body}, headers=headers)


@pytest.fixture
def use_fake(monkeypatch, paddle_settings):
    f = FakePaddle()
    import app.billing.paddle_checkout as pc
    monkeypatch.setattr(pc, "get_paddle_client", lambda: f)
    return f


def test_checkout_unauthenticated_is_rejected(client, db_session, paddle_settings):
    headers, org = register(client, "u@example.com")
    site = make_website(db_session, org)
    assert client.post(f"/api/v1/organizations/{org}/websites/{site.id}/billing/checkout", json={"interval": "month"}).status_code in (401, 403)


def test_checkout_with_no_plans_says_unavailable(client, db_session, use_fake):
    headers, org = register(client, "n@example.com")
    site = make_website(db_session, org)
    r = _checkout(client, org, site, headers)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "plans_unavailable"
    assert use_fake.calls == []


def test_checkout_unknown_plan(client, db_session, use_fake):
    headers, org = register(client, "p@example.com")
    site = make_website(db_session, org)
    assert _checkout(client, org, site, headers, plan_code="nope").status_code == 404


def test_checkout_sandbox_test_plan_allowed_with_trial_price(client, db_session, use_fake):
    headers, org = register(client, "s@example.com")
    site = make_website(db_session, org)
    make_plan(db_session)
    r = _checkout(client, org, site, headers, plan_code="pro_m")
    assert r.status_code == 200, r.text
    call = use_fake.calls[0]
    assert call["variant_id"] == "pri_trial" and call["custom_data"]["plan_code"] == "pro_m"
    assert r.json()["checkout_url"] == "https://pay.example/c" and r.json()["with_trial"] is True


def test_unapproved_plan_cannot_be_bought_in_live(client, db_session, use_fake, monkeypatch):
    monkeypatch.setattr(get_settings(), "paddle_env", "live")
    headers, org = register(client, "l@example.com")
    site = make_website(db_session, org)
    make_plan(db_session)  # test config, not approved
    r = _checkout(client, org, site, headers, plan_code="pro_m")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "plan_not_available"
    assert use_fake.calls == []


def test_approved_plan_can_be_bought_in_live(client, db_session, use_fake, monkeypatch):
    monkeypatch.setattr(get_settings(), "paddle_env", "live")
    headers, org = register(client, "la@example.com")
    site = make_website(db_session, org)
    make_plan(db_session, approved=True, test=False)
    assert _checkout(client, org, site, headers, plan_code="pro_m").status_code == 200


def test_plan_without_price_id_or_amount_is_not_sellable(client, db_session, use_fake):
    headers, org = register(client, "np@example.com")
    site = make_website(db_session, org)
    make_plan(db_session, code="a", price=None)
    make_plan(db_session, code="b", amount=None)
    make_plan(db_session, code="c", active=False)
    for code in "abc":
        assert _checkout(client, org, site, headers, plan_code=code).status_code == 409


def test_trial_used_switches_to_no_trial_price(client, db_session, use_fake):
    from app.models.billing import TrialHistory
    headers, org = register(client, "t@example.com")
    site = make_website(db_session, org)
    make_plan(db_session)
    db_session.add(TrialHistory(organization_id=site.organization_id, website_id=site.id, domain_key="shop.example", outcome="expired", started_at=T0))
    db_session.commit()
    r = _checkout(client, org, site, headers, plan_code="pro_m")
    assert r.status_code == 200 and use_fake.calls[0]["variant_id"] == "pri_notrial" and r.json()["with_trial"] is False


def test_checkout_provider_failure_is_a_clean_502_and_marks_failed(client, db_session, use_fake):
    use_fake.fail = ProviderError("boom")
    headers, org = register(client, "f@example.com")
    site = make_website(db_session, org)
    make_plan(db_session)
    assert _checkout(client, org, site, headers, plan_code="pro_m").status_code == 502
    assert db_session.query(CheckoutSession).one().status == CheckoutStatus.failed


def test_checkout_for_someone_elses_project_is_404(client, db_session, use_fake):
    ha, oa = register(client, "a@example.com")
    hb, ob = register(client, "b@example.com")
    site_b = make_website(db_session, ob, "b.example")
    make_plan(db_session)
    assert client.post(f"/api/v1/organizations/{oa}/websites/{site_b.id}/billing/checkout", json={"interval": "month", "plan_code": "pro_m"}, headers=ha).status_code in (403, 404)
    assert client.post(f"/api/v1/organizations/{ob}/websites/{site_b.id}/billing/checkout", json={"interval": "month", "plan_code": "pro_m"}, headers=ha).status_code in (403, 404)


def test_second_click_reuses_pending_checkout(client, db_session, use_fake):
    headers, org = register(client, "r@example.com")
    site = make_website(db_session, org)
    make_plan(db_session)
    _checkout(client, org, site, headers, plan_code="pro_m")
    _checkout(client, org, site, headers, plan_code="pro_m")
    assert db_session.query(CheckoutSession).filter(CheckoutSession.status == CheckoutStatus.pending).count() == 1
    assert len(use_fake.calls) == 1


# ---------------------------------------------------------------- catalogue / public pricing

def test_public_pricing_hides_unapproved_and_says_not_finalized(client, db_session, paddle_settings):
    make_plan(db_session)
    body = client.get("/api/v1/public/pricing").json()
    assert body["plans"] == [] and body["pricing_finalized"] is False


def test_public_pricing_shows_only_approved_public_priced_plans(client, db_session, paddle_settings):
    make_plan(db_session, code="ok", approved=True, test=False)
    make_plan(db_session, code="hidden", approved=True, test=False, public=False)
    make_plan(db_session, code="draft", approved=False)
    make_plan(db_session, code="noprice", approved=True, test=False, amount=None)
    body = client.get("/api/v1/public/pricing").json()
    assert [p["code"] for p in body["plans"]] == ["ok"] and body["pricing_finalized"] is True


# ---------------------------------------------------------------- entitlements & project limits

def _subscribe(db, site, plan, status=SubscriptionStatus.active):
    sub = Subscription(organization_id=site.organization_id, website_id=site.id, provider=SubscriptionProvider.paddle, provider_subscription_id=f"s_{uuid.uuid4().hex[:6]}",
                       status=status, billing_interval=plan.billing_interval, price_cents=plan.amount_cents, currency="USD", plan_id=plan.id)
    db.add(sub)
    db.commit()
    return sub


def test_feature_blocked_only_when_plan_says_so(db_session, client, paddle_settings):
    headers, org = register(client, "e@example.com")
    site = make_website(db_session, org)
    assert features.feature_blocked(db_session, site, "competitor_analysis") is False  # no plan => unrestricted
    plan = make_plan(db_session, entitlements_json={"competitor_analysis": False, "crawl": True})
    _subscribe(db_session, site, plan)
    assert features.feature_blocked(db_session, site, "competitor_analysis") is True
    assert features.feature_blocked(db_session, site, "crawl") is False
    assert features.feature_blocked(db_session, site, "scheduled_crawl") is False  # alias of crawl
    assert features.feature_blocked(db_session, site, "keyword_discovery") is False  # unspecified => not restricted


def test_usage_limits(db_session, client, paddle_settings):
    headers, org = register(client, "ul@example.com")
    site = make_website(db_session, org)
    plan = make_plan(db_session, limits_json={"competitor_domains": 2})
    _subscribe(db_session, site, plan)
    assert features.within_usage_limit(db_session, site, "competitor_domains", 1)
    assert not features.within_usage_limit(db_session, site, "competitor_domains", 2)
    assert features.within_usage_limit(db_session, site, "reports_per_month", 10_000)


def test_project_capacity_unlimited_without_plan_and_capped_with_one(db_session, client, paddle_settings):
    headers, org = register(client, "cap@example.com")
    site = make_website(db_session, org)
    assert features.project_capacity(db_session, site.organization_id).limit is None
    plan = make_plan(db_session, max_projects=1, max_websites=3)
    _subscribe(db_session, site, plan)
    cap = features.project_capacity(db_session, site.organization_id)
    assert (cap.limit, cap.used, cap.reached) == (1, 1, True)


def test_project_limit_enforced_on_direct_api_but_only_in_enforce_mode(client, db_session, paddle_settings, monkeypatch):
    headers, org = register(client, "lim@example.com")
    site = make_website(db_session, org)
    _subscribe(db_session, site, make_plan(db_session, max_projects=1))
    import socket
    from app.core import url_safety
    monkeypatch.setattr(url_safety.socket, "getaddrinfo", lambda host, port: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))])
    body = {"url": "https://second.example/", "display_name": "Second"}
    path = f"/api/v1/organizations/{org}/websites"
    monkeypatch.setattr(get_settings(), "billing_enforcement", "enforce")
    r = client.post(path, json=body, headers=headers)
    assert r.status_code == 402 and r.json()["detail"]["code"] == "project_limit_reached", r.text
    monkeypatch.setattr(get_settings(), "billing_enforcement", "off")
    assert client.post(path, json=body, headers=headers).status_code in (200, 201)


def test_expired_subscription_stops_counting_toward_capacity(db_session, client, paddle_settings):
    headers, org = register(client, "ex@example.com")
    site = make_website(db_session, org)
    _subscribe(db_session, site, make_plan(db_session, max_projects=1), status=SubscriptionStatus.expired)
    assert features.project_capacity(db_session, site.organization_id).limit is None
    assert db_session.get(Website, site.id) is not None  # data preserved


# ---------------------------------------------------------------- cancel / change plan / invoice isolation

def test_cancel_requires_ownership_and_does_not_change_local_state(client, db_session, setup, monkeypatch):
    headers, org, site, plan, session, _ = setup
    post(client, sub_event(session, status="active"))
    sub = the_sub(db_session)
    calls = []

    class C:
        def cancel_subscription(self, sid, immediately=False):
            calls.append(sid)
    import app.api.v1.endpoints.billing as b
    monkeypatch.setattr(b, "get_paddle_client", lambda: C())
    other_h, other_org = register(client, "other@example.com")
    assert client.post(f"/api/v1/organizations/{other_org}/billing/subscriptions/{sub.id}/cancel", headers=other_h).status_code in (403, 404)
    assert calls == []
    r = client.post(f"/api/v1/organizations/{org}/billing/subscriptions/{sub.id}/cancel", headers=headers)
    assert r.status_code in (200, 202), r.text
    assert calls == ["sub_01"]
    db_session.refresh(sub)
    assert sub.status == SubscriptionStatus.active  # only the webhook moves state


# ---------------------------------------------------------------- admin plan catalogue

ADMIN = "qaqadeer@gmail.com"


@pytest.fixture
def admin(client, db_session, paddle_settings):
    headers, org = register(client, ADMIN)
    user = db_session.query(User).filter(User.email == ADMIN).one()
    user.email_verified_at = datetime.now(timezone.utc)
    db_session.commit()
    return headers


def _new(code="starter_m", **kw):
    return {"code": code, "name": "Starter", "billing_interval": "month", "reason": "test", "confirm": True, **kw}


def test_admin_plan_endpoints_reject_non_admins_and_anonymous(client, db_session, paddle_settings):
    headers, _ = register(client, "notadmin@example.com")
    for method, path in (("get", "/api/v1/admin/billing/plans"), ("post", "/api/v1/admin/billing/plans"), ("get", "/api/v1/admin/billing/customers")):
        assert getattr(client, method)(path).status_code in (401, 403)
        assert getattr(client, method)(path, headers=headers).status_code == 403


def test_admin_creates_plan_unpriced_inactive_and_audited(client, db_session, admin):
    from app.models.audit_event import AuditEvent
    r = client.post("/api/v1/admin/billing/plans", json=_new(), headers=admin)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["amount_cents"] is None and body["is_active"] is False and body["is_approved"] is False and body["publicly_visible"] is False
    assert db_session.query(AuditEvent).filter(AuditEvent.action.like("%billing_plan.create")).count() == 1
    assert client.get("/api/v1/public/pricing").json()["plans"] == []


def test_admin_requires_reason_and_confirmation(client, admin):
    assert client.post("/api/v1/admin/billing/plans", json={**_new(), "confirm": False}, headers=admin).status_code == 422
    assert client.post("/api/v1/admin/billing/plans", json={**_new(), "reason": " "}, headers=admin).status_code == 422


def test_admin_rejects_unknown_features_negative_limits_bad_ids_and_duplicates(client, admin):
    assert client.post("/api/v1/admin/billing/plans", json=_new(entitlements={"made_up": True}), headers=admin).status_code == 422
    assert client.post("/api/v1/admin/billing/plans", json=_new(limits={"crawls_per_month": -1}), headers=admin).status_code == 422
    assert client.post("/api/v1/admin/billing/plans", json=_new(paddle_price_id="bogus"), headers=admin).status_code == 422
    assert client.post("/api/v1/admin/billing/plans", json=_new(), headers=admin).status_code == 201
    assert client.post("/api/v1/admin/billing/plans", json=_new(), headers=admin).status_code == 409
    assert client.post("/api/v1/admin/billing/plans", json=_new("x", is_approved=True), headers=admin).status_code == 422


def test_cannot_approve_without_price_mapping_or_while_test_config(client, admin):
    pid = client.post("/api/v1/admin/billing/plans", json=_new()).json() if False else client.post("/api/v1/admin/billing/plans", json=_new(), headers=admin).json()["id"]
    approve = lambda **kw: client.patch(f"/api/v1/admin/billing/plans/{pid}", json={"reason": "go", "confirm": True, "is_approved": True, **kw}, headers=admin)
    r = approve()
    assert r.status_code == 422 and r.json()["detail"]["code"] == "plan_not_ready"
    r = approve(amount_cents=2500, paddle_price_id="pri_01", is_test_config=False)  # trial_days 0 => no-trial price not needed
    assert r.status_code == 200 and r.json()["is_approved"] is True


def test_approved_plan_becomes_public_only_when_active_and_public(client, db_session, admin):
    pid = client.post("/api/v1/admin/billing/plans", json=_new(), headers=admin).json()["id"]
    patch = lambda **kw: client.patch(f"/api/v1/admin/billing/plans/{pid}", json={"reason": "r", "confirm": True, **kw}, headers=admin)
    assert patch(amount_cents=2500, paddle_price_id="pri_01", is_test_config=False, is_approved=True).status_code == 200
    assert client.get("/api/v1/public/pricing").json()["plans"] == []  # approved but still inactive / not public
    patch(is_active=True, is_public=True)
    pricing = client.get("/api/v1/public/pricing").json()
    assert pricing["pricing_finalized"] is True and pricing["plans"][0]["code"] == "starter_m" and pricing["plans"][0]["price_cents"] == 2500
    patch(is_approved=False)  # withdrawing approval hides it again
    assert client.get("/api/v1/public/pricing").json()["plans"] == []


def test_plan_code_is_immutable_and_listing_never_exposes_secrets(client, admin):
    pid = client.post("/api/v1/admin/billing/plans", json=_new(), headers=admin).json()["id"]
    assert client.patch(f"/api/v1/admin/billing/plans/{pid}", json={"reason": "r", "confirm": True, "code": "other"}, headers=admin).status_code == 422
    listing = client.get("/api/v1/admin/billing/plans", headers=admin).json()
    text = json.dumps(listing)
    assert SECRET not in text and "api_key\": \"" not in text
    assert listing["paddle"]["webhook_secret_set"] is True and "webhook_url" in listing["paddle"]
