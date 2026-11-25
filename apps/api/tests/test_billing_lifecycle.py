"""Phase 3: enforcement at the real gates, notifications on confirmed changes only, and the jobs
that keep local state honest."""

import json
import uuid
from datetime import timedelta
from types import SimpleNamespace

import pytest

from app.ai import runner as ai_runner
from app.api.v1.endpoints import crawls as crawls_endpoint
from app.billing import jobs, notifications
from app.billing.entitlement import EntitlementRequired
from app.billing.provider import ProviderError, ProviderNotConfigured
from app.config import get_settings
from app.models.billing import (
    BillingEvent, BillingEventStatus, BillingInterval, Payment, Subscription, SubscriptionProvider, SubscriptionStatus, TrialHistory,
)
from app.models.organization import Organization
from app.models.user import User
from app.models.website import VerificationStatus, Website
from tests.billing_helpers import (
    NOW, billing_settings, invoice_body, make_session, make_website, post_webhook, register, subscription_body,  # noqa: F401
)


def _grant(db_session, site, status=SubscriptionStatus.active, **fields):
    sub = Subscription(organization_id=site.organization_id, website_id=site.id, provider=SubscriptionProvider.lemonsqueezy,
                       provider_subscription_id=uuid.uuid4().hex[:10], status=status, billing_interval=BillingInterval.month,
                       price_cents=1500, **fields)
    db_session.add(sub)
    db_session.commit()
    return sub


@pytest.fixture
def enforce(monkeypatch):
    monkeypatch.setattr(get_settings(), "billing_enforcement", "enforce")


# --- enforcement at the gates ----------------------------------------------------------------

def test_a_manual_crawl_needs_an_entitlement_only_in_enforce_mode(client, db_session, monkeypatch):
    headers, org = register(client, "gate-crawl@example.com")
    site = make_website(db_session, org)
    monkeypatch.setattr(crawls_endpoint.run_site_crawl, "delay", lambda *a: None)
    url = f"/api/v1/organizations/{org}/websites/{site.id}/crawls"

    assert client.post(url, headers=headers).status_code in (200, 201, 202)  # mode off: unchanged behaviour

    monkeypatch.setattr(get_settings(), "billing_enforcement", "enforce")
    blocked = client.post(url, headers=headers)
    assert blocked.status_code == 402
    assert blocked.json()["detail"]["code"] == "subscription_required"
    assert blocked.json()["detail"]["reason"] == "no_subscription"

    # a finished crawl does not hold the next one back, so entitle the project and try again
    from app.models.crawl_job import CrawlJob
    db_session.query(CrawlJob).delete()
    _grant(db_session, site)
    assert client.post(url, headers=headers).status_code in (200, 201, 202)


def test_project_a_paying_does_not_unlock_project_b(client, db_session, enforce, monkeypatch):
    headers, org = register(client, "ab@example.com")
    a, b = make_website(db_session, org, "a.example"), make_website(db_session, org, "b.example")
    _grant(db_session, a)
    monkeypatch.setattr(crawls_endpoint.run_site_crawl, "delay", lambda *a: None)
    assert client.post(f"/api/v1/organizations/{org}/websites/{a.id}/crawls", headers=headers).status_code in (200, 201, 202)
    assert client.post(f"/api/v1/organizations/{org}/websites/{b.id}/crawls", headers=headers).status_code == 402


def test_ai_work_is_blocked_before_any_provider_call_when_not_entitled(db_session, enforce, monkeypatch):
    org = Organization(name="AI Gate", slug=f"aig-{uuid.uuid4().hex[:8]}")
    db_session.add(org)
    db_session.flush()
    site = Website(organization_id=org.id, canonical_url="https://ai.example/", hostname="ai.example", display_name="ai")
    db_session.add(site)
    db_session.commit()
    touched = []
    monkeypatch.setattr(ai_runner, "get_openai_client", lambda: touched.append(1))

    from app.models.agent_run import AgentType
    with pytest.raises(EntitlementRequired):
        ai_runner.run_ai_agent(db_session, site, AgentType.keyword_discovery, site.id, system_prompt="s", user_prompt="u",
                               response_json_schema={}, parse_fn=lambda raw: raw)
    assert touched == []  # no provider client was even created

    _grant(db_session, site)
    with pytest.raises(Exception) as exc:  # now it gets as far as the (stubbed) client
        ai_runner.run_ai_agent(db_session, site, AgentType.keyword_discovery, site.id, system_prompt="s", user_prompt="u",
                               response_json_schema={}, parse_fn=lambda raw: raw)
    assert not isinstance(exc.value, EntitlementRequired) and touched == [1]


def test_the_ai_endpoints_degrade_cleanly_for_an_unsubscribed_project(client, db_session, enforce):
    headers, org = register(client, "ai-503@example.com")
    site = make_website(db_session, org)
    r = client.post(f"/api/v1/organizations/{org}/websites/{site.id}/keyword-discovery/run", json={}, headers=headers)
    # the endpoint now refuses up front with a structured 402 (it used to fail later with a 503 from the AI layer)
    assert r.status_code == 402 and r.json()["detail"]["code"] == "subscription_required" and "subscription" in r.json()["detail"]["message"].lower()


def test_applying_a_change_to_a_live_site_needs_an_entitlement(db_session, enforce):
    from app.execution import service as execution_service
    from tests.test_execution_service import _make_user, _make_website_and_opportunity, _proposal

    website, opportunity = _make_website_and_opportunity(db_session)
    task = execution_service.create_tasks_from_proposal(db_session, website, opportunity, _proposal(opportunity.id),
                                                        requested_by=_make_user(db_session).id)[0]
    with pytest.raises(execution_service.ExecutionBlocked, match="no subscription"):
        execution_service.execute_task(db_session, website, task)


def test_scheduled_crawls_skip_projects_without_an_entitlement(db_session, enforce, monkeypatch):
    from app.tasks import scheduler as scheduler_module

    def site(host):
        org = Organization(name="Sched", slug=f"sch-{uuid.uuid4().hex[:8]}")
        db_session.add(org)
        db_session.flush()
        s = Website(organization_id=org.id, canonical_url=f"https://{host}/", hostname=host, display_name=host,
                    verification_status=VerificationStatus.verified)
        db_session.add(s)
        db_session.flush()
        return s

    paying, free = site("paying.example"), site("free.example")
    _grant(db_session, paying)
    monkeypatch.setattr(scheduler_module, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(db_session, "close", lambda: None)
    queued = []
    import app.tasks.crawl as crawl_module
    monkeypatch.setattr(crawl_module.run_site_crawl, "delay", lambda site_id, job_id: queued.append(site_id))

    assert scheduler_module.daily_crawl_all_active_websites() == 1
    assert queued == [str(paying.id)]


# --- notifications ---------------------------------------------------------------------------

@pytest.fixture
def sent(monkeypatch):
    calls = []
    monkeypatch.setattr(notifications, "notify_organization", lambda db, org, **kw: calls.append(kw["event_type"]))
    return calls


@pytest.fixture
def paid_setup(client, db_session, billing_settings):
    headers, org = register(client, "notify@example.com")
    user = db_session.query(User).filter(User.email == "notify@example.com").one()
    site = make_website(db_session, org)
    return make_session(db_session, site, user.id), site


def test_each_confirmed_change_sends_one_message_and_replays_send_none(client, paid_setup, sent):
    session, _ = paid_setup
    raw = json.dumps(subscription_body(reference=session.reference)).encode()
    post_webhook(client, raw)
    post_webhook(client, raw)  # exact redelivery
    assert sent == ["billing_trial_started"]

    post_webhook(client, subscription_body(event="subscription_updated", status="active", reference=session.reference,
                                           updated=NOW + timedelta(days=7), trial_ends=NOW + timedelta(days=7)))
    post_webhook(client, invoice_body(updated=NOW + timedelta(days=7)))
    post_webhook(client, invoice_body(updated=NOW + timedelta(days=7, seconds=1)))  # same invoice, a different delivery
    assert sent == ["billing_trial_started", "billing_subscription_activated", "billing_payment_successful"]


def test_failure_recovery_cancellation_and_expiry_are_announced(client, paid_setup, sent):
    session, _ = paid_setup
    post_webhook(client, subscription_body(status="active", reference=session.reference, trial_ends=None))
    sent.clear()
    t = NOW + timedelta(days=30)
    post_webhook(client, subscription_body(event="subscription_updated", status="past_due", reference=session.reference, updated=t, trial_ends=None))
    post_webhook(client, invoice_body(event="subscription_payment_failed", invoice_id="9100", status="pending", reason="renewal", updated=t))
    post_webhook(client, invoice_body(event="subscription_payment_recovered", invoice_id="9100", reason="renewal", updated=t + timedelta(hours=1)))
    post_webhook(client, subscription_body(event="subscription_cancelled", status="cancelled", cancelled=True, reference=session.reference,
                                           updated=t + timedelta(days=1), trial_ends=None, ends_at=t + timedelta(days=9)))
    post_webhook(client, subscription_body(event="subscription_expired", status="expired", reference=session.reference,
                                           updated=t + timedelta(days=10), trial_ends=None))
    assert sent == ["billing_payment_failed", "billing_payment_recovered", "billing_cancellation_scheduled", "billing_subscription_expired"]


def test_a_rejected_webhook_sends_nothing(client, paid_setup, sent):
    session, _ = paid_setup
    post_webhook(client, subscription_body(reference=session.reference), signature="bad")
    assert sent == []


def test_a_broken_mail_system_never_undoes_a_payment(client, db_session, paid_setup, monkeypatch):
    session, _ = paid_setup

    def boom(*a, **k):
        raise RuntimeError("smtp down")

    monkeypatch.setattr(notifications, "notify_organization", boom)
    r = post_webhook(client, subscription_body(reference=session.reference))
    assert r.status_code == 200 and r.json()["status"] == "processed"
    assert db_session.query(Subscription).count() == 1


# --- jobs ------------------------------------------------------------------------------------

class ReconcileProvider:
    def __init__(self, body=None, error=None):
        self.body, self.error, self.calls = body, error, []

    def get_subscription(self, provider_subscription_id):
        self.calls.append(provider_subscription_id)
        if self.error:
            raise self.error
        return self.body

    create_checkout = cancel_subscription = None


def _linked(client, db_session, session, **kwargs):
    post_webhook(client, subscription_body(reference=session.reference, **kwargs))
    return db_session.query(Subscription).one()


def test_reconciliation_repairs_a_missed_cancellation(client, db_session, paid_setup, sent):
    session, _ = paid_setup
    sub = _linked(client, db_session, session)
    missed = subscription_body(event="subscription_cancelled", status="cancelled", cancelled=True, reference=session.reference,
                               updated=NOW + timedelta(days=2), ends_at=NOW + timedelta(days=7))
    provider = ReconcileProvider(body={"data": missed["data"]})

    result = jobs.reconcile_subscriptions(db_session, provider=provider, now=NOW + timedelta(days=3))

    assert result == {"checked": 1, "changed": 1, "failed": 0}
    db_session.refresh(sub)
    assert sub.status == SubscriptionStatus.cancelled and sub.ends_at == NOW + timedelta(days=7)
    assert "billing_cancellation_scheduled" in sent


def test_reconciliation_leaves_fresh_subscriptions_alone_and_survives_provider_errors(client, db_session, paid_setup):
    session, _ = paid_setup
    sub = _linked(client, db_session, session)
    fresh = ReconcileProvider(body={"data": {}})
    assert jobs.reconcile_subscriptions(db_session, provider=fresh, now=NOW + timedelta(hours=1))["checked"] == 0
    assert fresh.calls == []

    failing = ReconcileProvider(error=ProviderError("down"))
    assert jobs.reconcile_subscriptions(db_session, provider=failing, now=NOW + timedelta(days=3))["failed"] == 1
    db_session.refresh(sub)
    assert sub.status == SubscriptionStatus.trialing  # unchanged


def test_reconciliation_does_nothing_when_billing_is_not_configured(db_session, monkeypatch):
    def not_configured():
        raise ProviderNotConfigured("no key")

    monkeypatch.setattr(jobs, "get_provider", not_configured)
    assert jobs.reconcile_subscriptions(db_session) == {"checked": 0, "changed": 0, "failed": 0}


def test_a_cancelled_subscription_past_its_end_date_expires(client, db_session, paid_setup, sent):
    session, site = paid_setup
    _linked(client, db_session, session)
    post_webhook(client, subscription_body(event="subscription_cancelled", status="cancelled", cancelled=True, reference=session.reference,
                                           updated=NOW + timedelta(days=1), ends_at=NOW + timedelta(days=7)))
    assert jobs.expire_finished(db_session, now=NOW + timedelta(days=6)) == 0
    assert jobs.expire_finished(db_session, now=NOW + timedelta(days=8)) == 1
    assert jobs.expire_finished(db_session, now=NOW + timedelta(days=9)) == 0  # idempotent
    assert db_session.query(Subscription).one().status == SubscriptionStatus.expired
    # it was cancelled during the trial, and that outcome is kept (not rewritten to "expired")
    assert db_session.query(TrialHistory).filter(TrialHistory.website_id == site.id).one().outcome == "cancelled"


def test_the_trial_reminder_is_sent_once_and_only_near_the_end(client, db_session, paid_setup, sent):
    session, _ = paid_setup
    _linked(client, db_session, session)
    sent.clear()
    assert jobs.send_trial_reminders(db_session, now=NOW + timedelta(days=1)) == 0
    assert jobs.send_trial_reminders(db_session, now=NOW + timedelta(days=5)) == 1
    assert jobs.send_trial_reminders(db_session, now=NOW + timedelta(days=6)) == 0
    assert sent == ["billing_trial_ending_soon"]


def test_an_event_that_arrived_too_early_is_applied_by_the_retry_job(client, db_session, paid_setup):
    session, _ = paid_setup
    assert post_webhook(client, invoice_body()).status_code == 503
    post_webhook(client, subscription_body(reference=session.reference))
    assert db_session.query(Payment).count() == 0

    assert jobs.retry_failed_events(db_session) == 1
    assert db_session.query(Payment).one().amount_cents == 1500
    assert jobs.retry_failed_events(db_session) == 0  # nothing left to retry
    assert db_session.query(BillingEvent).filter(BillingEvent.status == BillingEventStatus.failed).count() == 0
