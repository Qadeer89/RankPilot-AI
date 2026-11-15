"""Guided onboarding: every step's completion must reflect real
application state, computed live -- not a flag that can drift out of
sync (Part 3 of the onboarding spec: "If Google Search Console is
already connected, automatically mark that step as completed.")."""

import uuid
from datetime import datetime, timezone

from app.models.crawl_job import CrawlJob, CrawlStatus, CrawlTrigger
from app.models.oauth_connection import OAuthConnection, OAuthConnectionStatus, OAuthProvider
from app.models.organization import Organization
from app.models.seo_finding import FindingSeverity, FindingStatus, SEOFinding
from app.models.user import User
from app.models.website import VerificationStatus, Website, WebsiteStatus
from app.models.website_connection import ConnectorType, WebsiteConnection, WebsiteConnectionStatus
from app.onboarding import service as onboarding_service


def _make_org(db_session, name="Onboarding Org"):
    org = Organization(name=name, slug=f"onboard-{uuid.uuid4().hex[:8]}")
    db_session.add(org)
    db_session.flush()
    return org


def _make_website(db_session, org, *, verified=False):
    website = Website(
        organization_id=org.id,
        canonical_url="https://example.com/",
        hostname="example.com",
        display_name="Example",
        verification_status=VerificationStatus.verified if verified else VerificationStatus.unverified,
        status=WebsiteStatus.active,
    )
    db_session.add(website)
    db_session.flush()
    return website


def _status_by_key(result, key):
    return next(s for s in result["steps"] if s["key"] == key)


def test_fresh_org_has_no_steps_completed(db_session):
    org = _make_org(db_session)
    result = onboarding_service.get_onboarding_status(db_session, org.id)
    assert _status_by_key(result, "welcome")["completed"] is False
    assert _status_by_key(result, "add_website")["completed"] is False
    assert result["all_mandatory_complete"] is False


def test_dismiss_welcome_marks_step_complete(db_session):
    org = _make_org(db_session)
    onboarding_service.dismiss_welcome(db_session, org.id)
    result = onboarding_service.get_onboarding_status(db_session, org.id)
    assert _status_by_key(result, "welcome")["completed"] is True


def test_add_website_marks_step_complete_automatically(db_session):
    org = _make_org(db_session)
    _make_website(db_session, org)
    result = onboarding_service.get_onboarding_status(db_session, org.id)
    assert _status_by_key(result, "add_website")["completed"] is True
    # But verification is a separate, still-incomplete step.
    assert _status_by_key(result, "verify_website")["completed"] is False


def test_verified_website_marks_verify_step_complete(db_session):
    org = _make_org(db_session)
    _make_website(db_session, org, verified=True)
    result = onboarding_service.get_onboarding_status(db_session, org.id)
    assert _status_by_key(result, "verify_website")["completed"] is True


def test_connected_cms_marks_connect_cms_step_complete(db_session):
    org = _make_org(db_session)
    website = _make_website(db_session, org, verified=True)
    db_session.add(
        WebsiteConnection(
            website_id=website.id,
            connector_type=ConnectorType.wordpress,
            encrypted_secret_reference="x",
            config_json={},
            granted_scopes=[],
            status=WebsiteConnectionStatus.connected,
        )
    )
    db_session.flush()
    result = onboarding_service.get_onboarding_status(db_session, org.id)
    assert _status_by_key(result, "connect_cms")["completed"] is True


def test_disconnected_cms_does_not_count(db_session):
    org = _make_org(db_session)
    website = _make_website(db_session, org, verified=True)
    db_session.add(
        WebsiteConnection(
            website_id=website.id,
            connector_type=ConnectorType.wordpress,
            encrypted_secret_reference="x",
            config_json={},
            granted_scopes=[],
            status=WebsiteConnectionStatus.disconnected,
        )
    )
    db_session.flush()
    result = onboarding_service.get_onboarding_status(db_session, org.id)
    assert _status_by_key(result, "connect_cms")["completed"] is False


def test_already_connected_gsc_marks_step_complete_without_any_onboarding_action(db_session):
    # Exactly the spec's example: a pre-existing connection is detected
    # automatically, not re-prompted for.
    org = _make_org(db_session)
    db_session.add(
        OAuthConnection(
            organization_id=org.id,
            provider=OAuthProvider.google_search_console,
            encrypted_token_reference="x",
            status=OAuthConnectionStatus.connected,
        )
    )
    db_session.flush()
    result = onboarding_service.get_onboarding_status(db_session, org.id)
    assert _status_by_key(result, "connect_gsc")["completed"] is True
    assert _status_by_key(result, "connect_ga4")["completed"] is False


def test_completed_crawl_marks_first_audit_step_complete(db_session):
    org = _make_org(db_session)
    website = _make_website(db_session, org, verified=True)
    db_session.add(
        CrawlJob(
            website_id=website.id,
            trigger=CrawlTrigger.manual,
            status=CrawlStatus.completed,
            started_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
        )
    )
    db_session.flush()
    result = onboarding_service.get_onboarding_status(db_session, org.id)
    assert _status_by_key(result, "configure_crawling")["completed"] is True
    assert _status_by_key(result, "first_audit")["completed"] is True
    assert _status_by_key(result, "review_findings")["completed"] is True


def test_pending_crawl_does_not_complete_first_audit(db_session):
    org = _make_org(db_session)
    website = _make_website(db_session, org, verified=True)
    db_session.add(CrawlJob(website_id=website.id, trigger=CrawlTrigger.manual, status=CrawlStatus.pending))
    db_session.flush()
    result = onboarding_service.get_onboarding_status(db_session, org.id)
    assert _status_by_key(result, "configure_crawling")["completed"] is True
    assert _status_by_key(result, "first_audit")["completed"] is False


def test_skip_optional_step(db_session):
    org = _make_org(db_session)
    onboarding_service.skip_step(db_session, org.id, "connect_cms")
    result = onboarding_service.get_onboarding_status(db_session, org.id)
    step = _status_by_key(result, "connect_cms")
    assert step["skipped"] is True
    assert step["completed"] is False


def test_cannot_skip_a_mandatory_step(db_session):
    org = _make_org(db_session)
    try:
        onboarding_service.skip_step(db_session, org.id, "add_website")
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_unskip_reverses_a_skip(db_session):
    org = _make_org(db_session)
    onboarding_service.skip_step(db_session, org.id, "connect_cms")
    onboarding_service.unskip_step(db_session, org.id, "connect_cms")
    result = onboarding_service.get_onboarding_status(db_session, org.id)
    assert _status_by_key(result, "connect_cms")["skipped"] is False


def test_mark_complete_refuses_when_mandatory_steps_remain(db_session):
    org = _make_org(db_session)
    completed = onboarding_service.mark_complete_if_ready(db_session, org.id)
    assert completed is False
    result = onboarding_service.get_onboarding_status(db_session, org.id)
    assert result["completed_at"] is None


def test_mark_complete_succeeds_once_every_mandatory_step_is_done(db_session):
    org = _make_org(db_session)
    onboarding_service.dismiss_welcome(db_session, org.id)
    website = _make_website(db_session, org, verified=True)
    website.automation_policy = {"auto_execute_risk_tier_1": True}
    db_session.add(
        CrawlJob(
            website_id=website.id,
            trigger=CrawlTrigger.manual,
            status=CrawlStatus.completed,
            started_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
        )
    )
    db_session.flush()

    completed = onboarding_service.mark_complete_if_ready(db_session, org.id)
    assert completed is True
    result = onboarding_service.get_onboarding_status(db_session, org.id)
    assert result["completed_at"] is not None
    assert result["all_mandatory_complete"] is True


def test_onboarding_state_is_isolated_per_organization(db_session):
    org_a = _make_org(db_session, "Org A")
    org_b = _make_org(db_session, "Org B")
    onboarding_service.dismiss_welcome(db_session, org_a.id)

    result_a = onboarding_service.get_onboarding_status(db_session, org_a.id)
    result_b = onboarding_service.get_onboarding_status(db_session, org_b.id)
    assert _status_by_key(result_a, "welcome")["completed"] is True
    assert _status_by_key(result_b, "welcome")["completed"] is False


def test_onboarding_api_requires_membership(client, db_session):
    other_org = _make_org(db_session)
    register = client.post(
        "/api/v1/auth/register",
        json={"email": "onboard-api@example.com", "password": "correct-horse-battery", "organization_name": "My Org"},
    )
    token = register.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    response = client.get(f"/api/v1/organizations/{other_org.id}/onboarding", headers=headers)
    assert response.status_code == 403


def test_onboarding_api_full_flow(client, db_session):
    register = client.post(
        "/api/v1/auth/register",
        json={"email": "onboard-flow@example.com", "password": "correct-horse-battery", "organization_name": "Flow Org"},
    )
    token = register.json()["access_token"]
    me = client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    org_id = me.json()["organizations"][0]["id"]
    headers = {"Authorization": f"Bearer {token}"}

    initial = client.get(f"/api/v1/organizations/{org_id}/onboarding", headers=headers)
    assert initial.status_code == 200
    assert initial.json()["all_mandatory_complete"] is False

    dismiss = client.post(f"/api/v1/organizations/{org_id}/onboarding/dismiss-welcome", headers=headers)
    assert dismiss.status_code == 200
    assert _status_by_key(dismiss.json(), "welcome")["completed"] is True

    skip = client.post(
        f"/api/v1/organizations/{org_id}/onboarding/skip", json={"step_key": "connect_cms"}, headers=headers
    )
    assert skip.status_code == 200
    assert _status_by_key(skip.json(), "connect_cms")["skipped"] is True

    bad_skip = client.post(
        f"/api/v1/organizations/{org_id}/onboarding/skip", json={"step_key": "add_website"}, headers=headers
    )
    assert bad_skip.status_code == 400
