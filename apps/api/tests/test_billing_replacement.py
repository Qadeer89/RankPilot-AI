import threading
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.billing import notifications
from app.billing.checkout import start_checkout
from app.billing.entitlement import evaluate
from app.billing.replacement import ReplacementError, grant_replacement_exception, replace_project
from app.db.session import SessionLocal
from app.models.audit_event import AuditEvent
from app.models.billing import (
    BillingInterval, Payment, PaymentStatus, ProjectReplacement, Subscription, SubscriptionProvider, SubscriptionStatus, TrialHistory,
)
from app.models.membership import Membership, MembershipRole
from app.models.organization import Organization
from app.models.user import User
from app.models.website import Website
from tests.billing_helpers import FakeProvider, billing_settings, make_website, register  # noqa: F401

T0 = datetime(2026, 11, 16, 10, 0, tzinfo=timezone.utc)


def _setup(client, db_session, email, *, status=SubscriptionStatus.trialing, projects=3):
    headers, org = register(client, email)
    user = db_session.query(User).filter(User.email == email).one()
    sites = [make_website(db_session, org, f"p{i}-{uuid.uuid4().hex[:4]}.example") for i in range(projects)]
    sub = Subscription(
        organization_id=sites[0].organization_id, user_id=user.id, website_id=sites[0].id, provider=SubscriptionProvider.lemonsqueezy,
        provider_subscription_id=uuid.uuid4().hex[:10], provider_customer_id="cust-1", status=status, billing_interval=BillingInterval.year,
        price_cents=15000, trial_started_at=T0, trial_ends_at=T0 + timedelta(days=7), renews_at=T0 + timedelta(days=7), created_at=T0,
    )
    db_session.add(sub)
    db_session.flush()
    db_session.add(TrialHistory(website_id=sites[0].id, organization_id=sub.organization_id, subscription_id=sub.id,
                                started_at=T0, ends_at=T0 + timedelta(days=7), outcome="active"))
    db_session.add(Payment(subscription_id=sub.id, organization_id=sub.organization_id, website_id=sites[0].id, user_id=user.id,
                           provider=SubscriptionProvider.lemonsqueezy, provider_payment_key=f"invoice:{uuid.uuid4().hex[:6]}",
                           amount_cents=15000, status=PaymentStatus.paid))
    db_session.commit()
    return headers, org, user, sites, sub


def _url(org, sub, tail="replace-project"):
    return f"/api/v1/organizations/{org}/billing/subscriptions/{sub.id}/{tail}"


def _body(target, **flags):
    return {"target_website_id": str(target.id), "confirm": True, "acknowledge_permanent": True, **flags}


@pytest.fixture
def sent(monkeypatch):
    calls = []
    monkeypatch.setattr(notifications, "notify_organization", lambda db, org, **kw: calls.append(kw["event_type"]))
    return calls


def test_a_valid_replacement_moves_only_the_project(client, db_session, sent):
    headers, org, user, (old, new, _), sub = _setup(client, db_session, "rep1@example.com")
    before = {c: getattr(sub, c) for c in ("id", "provider_customer_id", "provider_subscription_id", "billing_interval", "price_cents",
                                           "renews_at", "trial_started_at", "trial_ends_at", "created_at", "status")}
    payments_before = db_session.query(Payment).count()

    r = client.post(_url(org, sub), json=_body(new), headers=headers)

    assert r.status_code == 200, r.text
    assert r.json()["website_id"] == str(new.id) and r.json()["replacements_remaining"] == 0
    db_session.expire_all()
    sub = db_session.get(Subscription, sub.id)
    assert sub.website_id == new.id and sub.replacements_used == 1
    assert {c: getattr(sub, c) for c in before} == before  # billing identity untouched
    assert db_session.query(Payment).count() == payments_before and db_session.query(Subscription).count() == 1  # no new payment/subscription
    # entitlement moved with it
    assert evaluate(db_session, new, now=T0 + timedelta(days=1)).entitled is True
    assert evaluate(db_session, old, now=T0 + timedelta(days=1)).entitled is False
    record = db_session.query(ProjectReplacement).one()
    assert (record.from_website_id, record.to_website_id, record.sequence, record.admin_override) == (old.id, new.id, 1, False)
    audit = db_session.query(AuditEvent).filter(AuditEvent.action == "billing.project_replaced").one()
    assert audit.metadata_json["from_website_id"] == str(old.id) and audit.metadata_json["to_website_id"] == str(new.id)
    assert sent == ["billing_project_replaced", "billing_replacement_allowance_consumed"]


def test_the_trial_is_not_restarted_and_the_new_project_cannot_claim_another(client, db_session, billing_settings, monkeypatch):
    headers, org, user, (old, new, _), sub = _setup(client, db_session, "rep2@example.com")
    client.post(_url(org, sub), json=_body(new), headers=headers)
    db_session.expire_all()
    sub = db_session.get(Subscription, sub.id)
    assert (sub.trial_started_at, sub.trial_ends_at) == (T0, T0 + timedelta(days=7))

    trial_rows = {t.website_id: t for t in db_session.query(TrialHistory).all()}
    assert set(trial_rows) == {old.id, new.id}
    assert trial_rows[new.id].started_at == T0 and trial_rows[new.id].subscription_id == sub.id

    # the subscription ends; subscribing the new project again must not give a second trial
    sub.status = SubscriptionStatus.expired
    db_session.commit()
    from app.billing import checkout as checkout_module
    provider = FakeProvider()
    monkeypatch.setattr(checkout_module, "get_provider", lambda: provider)
    organization = db_session.get(Organization, sub.organization_id)
    offer = start_checkout(db_session, user=user, organization=organization, website=new, interval=BillingInterval.month, provider=provider)
    assert offer.with_trial is False and provider.calls[0]["variant_id"] == "113"


@pytest.mark.parametrize("name,flags", [("a", dict(confirm=False)), ("b", dict(acknowledge_permanent=False)),
                                         ("c", dict(confirm=False, acknowledge_permanent=False))])
def test_a_replacement_needs_both_confirmations(client, db_session, name, flags):
    headers, org, _, (_, new, _), sub = _setup(client, db_session, f"rep3-{name}@example.com")
    r = client.post(_url(org, sub), json=_body(new, **flags), headers=headers)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "confirmation_required"
    assert db_session.get(Subscription, sub.id).replacements_used == 0


def test_only_workspace_admins_can_replace_and_strangers_cannot_see_the_subscription(client, db_session):
    headers, org, _, (_, new, _), sub = _setup(client, db_session, "rep4@example.com")
    editor_headers, _ = register(client, "rep4-editor@example.com")
    editor = db_session.query(User).filter(User.email == "rep4-editor@example.com").one()
    db_session.add(Membership(organization_id=uuid.UUID(org), user_id=editor.id, role=MembershipRole.editor))
    db_session.commit()
    stranger_headers, stranger_org = register(client, "rep4-stranger@example.com")

    assert client.post(_url(org, sub), json=_body(new), headers=editor_headers).status_code == 403
    assert client.post(_url(org, sub), json=_body(new), headers=stranger_headers).status_code == 403
    assert client.post(_url(stranger_org, sub), json=_body(new), headers=stranger_headers).status_code == 404  # not theirs
    assert db_session.get(Subscription, sub.id).replacements_used == 0


def test_a_project_from_another_workspace_or_a_missing_one_is_refused_identically(client, db_session):
    headers, org, _, _, sub = _setup(client, db_session, "rep5@example.com")
    _, other_org = register(client, "rep5-other@example.com")
    foreign = make_website(db_session, other_org, "foreign.example")

    a = client.post(_url(org, sub), json=_body(foreign), headers=headers)
    b = client.post(_url(org, sub), json={"target_website_id": str(uuid.uuid4()), "confirm": True, "acknowledge_permanent": True}, headers=headers)
    assert (a.status_code, b.status_code) == (404, 404)
    assert a.json()["detail"] == b.json()["detail"]  # nothing about other tenants leaks
    assert db_session.get(Subscription, sub.id).replacements_used == 0


def test_a_project_that_already_has_a_subscription_cannot_receive_another(client, db_session):
    headers, org, user, (_, new, _), sub = _setup(client, db_session, "rep6@example.com")
    db_session.add(Subscription(organization_id=new.organization_id, website_id=new.id, provider=SubscriptionProvider.lemonsqueezy,
                                provider_subscription_id="other", status=SubscriptionStatus.active, billing_interval=BillingInterval.month,
                                price_cents=1500))
    db_session.commit()
    r = client.post(_url(org, sub), json=_body(new), headers=headers)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "target_subscribed"
    assert db_session.get(Subscription, sub.id).replacements_used == 0


def test_the_same_project_and_finished_subscriptions_are_refused(client, db_session):
    headers, org, _, (old, new, _), sub = _setup(client, db_session, "rep7@example.com")
    assert client.post(_url(org, sub), json=_body(old), headers=headers).json()["detail"]["code"] == "same_project"
    sub.status = SubscriptionStatus.expired
    db_session.commit()
    assert client.post(_url(org, sub), json=_body(new), headers=headers).json()["detail"]["code"] == "subscription_not_live"


def test_a_second_replacement_is_blocked_until_a_super_admin_grants_an_exception(client, db_session):
    headers, org, user, (a, b, c), sub = _setup(client, db_session, "rep8@example.com")
    assert client.post(_url(org, sub), json=_body(b), headers=headers).status_code == 200

    blocked = client.post(_url(org, sub), json=_body(c), headers=headers)
    assert blocked.status_code == 409 and blocked.json()["detail"]["code"] == "replacement_exhausted"

    with pytest.raises(ReplacementError, match="reason"):
        grant_replacement_exception(db_session, admin=user, subscription=db_session.get(Subscription, sub.id), reason="  ")
    grant_replacement_exception(db_session, admin=user, subscription=db_session.get(Subscription, sub.id), reason="Customer moved domains")
    db_session.commit()

    assert client.post(_url(org, sub), json=_body(c), headers=headers).status_code == 200
    seconds = db_session.query(ProjectReplacement).order_by(ProjectReplacement.sequence).all()
    assert [(r.sequence, r.admin_override) for r in seconds] == [(1, False), (2, True)]
    assert client.post(_url(org, sub), json=_body(a), headers=headers).status_code == 409  # exception was for one more only


@pytest.mark.parametrize("status,renews", [(SubscriptionStatus.active, T0 + timedelta(days=45)),
                                           (SubscriptionStatus.cancelled, None), (SubscriptionStatus.past_due, T0 + timedelta(days=3))])
def test_replacement_works_in_every_live_state_and_keeps_the_renewal_date(client, db_session, status, renews):
    headers, org, _, (_, new, _), sub = _setup(client, db_session, f"rep9-{status.value}@example.com", status=status)
    sub.renews_at, sub.ends_at = renews, (T0 + timedelta(days=9) if status == SubscriptionStatus.cancelled else None)
    db_session.commit()
    assert client.post(_url(org, sub), json=_body(new), headers=headers).status_code == 200
    db_session.expire_all()
    assert db_session.get(Subscription, sub.id).renews_at == renews


def test_targets_listing_offers_only_free_projects_of_the_same_workspace(client, db_session):
    headers, org, _, (a, b, c), sub = _setup(client, db_session, "rep10@example.com")
    db_session.add(Subscription(organization_id=c.organization_id, website_id=c.id, provider=SubscriptionProvider.lemonsqueezy,
                                provider_subscription_id="x", status=SubscriptionStatus.active, billing_interval=BillingInterval.month, price_cents=1500))
    db_session.commit()
    body = client.get(_url(org, sub, "replacement-targets"), headers=headers).json()
    assert body["replacements_remaining"] == 1
    assert [t["id"] for t in body["targets"]] == [str(b.id)]


def test_a_failure_part_way_leaves_everything_exactly_as_it_was(client, db_session, monkeypatch):
    headers, org, user, (old, new, _), sub = _setup(client, db_session, "rep11@example.com")
    import app.billing.replacement as module

    class Boom:
        def __init__(self, **kwargs):
            raise RuntimeError("disk full")

    monkeypatch.setattr(module, "ProjectReplacement", Boom)
    with pytest.raises(RuntimeError):
        replace_project(db_session, user=user, subscription_id=sub.id, target_website_id=new.id, organization_id=sub.organization_id)
    db_session.rollback()
    db_session.expire_all()
    sub = db_session.get(Subscription, sub.id)
    assert (sub.website_id, sub.replacements_used) == (old.id, 0)
    assert db_session.query(AuditEvent).filter(AuditEvent.action == "billing.project_replaced").count() == 0
    assert db_session.query(TrialHistory).filter(TrialHistory.website_id == new.id).count() == 0


def test_two_simultaneous_replacements_cannot_both_succeed():
    """Real, separate database connections (not the rolled-back test session): the row lock must serialize them."""
    setup = SessionLocal()
    tag = uuid.uuid4().hex[:8]
    org = Organization(name="Race", slug=f"race-{tag}")
    user = User(email=f"race-{tag}@example.com", hashed_password="x")
    setup.add_all([org, user])
    setup.flush()
    sites = [Website(organization_id=org.id, canonical_url=f"https://{tag}-{i}.example/", hostname=f"{tag}-{i}.example", display_name=str(i))
             for i in range(3)]
    setup.add_all(sites)
    setup.flush()
    sub = Subscription(organization_id=org.id, user_id=user.id, website_id=sites[0].id, provider=SubscriptionProvider.lemonsqueezy,
                       provider_subscription_id=f"race-{tag}", status=SubscriptionStatus.active, billing_interval=BillingInterval.month, price_cents=1500)
    setup.add(sub)
    setup.commit()
    ids = dict(org=org.id, user=user.id, sub=sub.id, targets=[sites[1].id, sites[2].id], all_sites=[s.id for s in sites])
    setup.close()

    results: list[str] = []
    barrier = threading.Barrier(2)

    def attempt(target_id):
        db = SessionLocal()
        try:
            user_row = db.get(User, ids["user"])
            barrier.wait()
            replace_project(db, user=user_row, subscription_id=ids["sub"], target_website_id=target_id, organization_id=ids["org"])
            db.commit()
            results.append("ok")
        except ReplacementError as exc:
            db.rollback()
            results.append(exc.code)
        finally:
            db.close()

    try:
        threads = [threading.Thread(target=attempt, args=(t,)) for t in ids["targets"]]
        [t.start() for t in threads]
        [t.join(timeout=30) for t in threads]
        assert sorted(results) == ["ok", "replacement_exhausted"]
        check = SessionLocal()
        assert check.get(Subscription, ids["sub"]).replacements_used == 1
        assert check.query(ProjectReplacement).filter(ProjectReplacement.subscription_id == ids["sub"]).count() == 1
        check.close()
    finally:
        cleanup = SessionLocal()
        cleanup.query(ProjectReplacement).filter(ProjectReplacement.subscription_id == ids["sub"]).delete()
        cleanup.query(AuditEvent).filter(AuditEvent.organization_id == ids["org"]).delete()
        cleanup.query(Subscription).filter(Subscription.id == ids["sub"]).delete()
        cleanup.query(Website).filter(Website.id.in_(ids["all_sites"])).delete(synchronize_session=False)
        cleanup.query(Organization).filter(Organization.id == ids["org"]).delete()
        cleanup.query(User).filter(User.id == ids["user"]).delete()
        cleanup.commit()
        cleanup.close()
