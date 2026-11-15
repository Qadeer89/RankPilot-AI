"""Performance timeline (spec section 9) and AI usage (section 12)."""

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest

from app.growth.performance import build_performance_timeline
from app.models.agent_run import AgentRun, AgentRunStatus, AgentType
from app.models.change_record import ChangeActorType, ChangeRecord, ValidationStatus
from app.models.keyword_observation import KeywordObservation
from app.models.organization import Organization
from app.models.page import Page
from app.models.seo_task import SEOTask
from app.models.user import User
from app.models.website import Website
from app.models.website_connection import ConnectorType


def _website_with_change(db_session, *, days_ago):
    org = Organization(name="Perf Org", slug=f"perf-{uuid.uuid4().hex[:8]}")
    db_session.add(org)
    db_session.flush()
    website = Website(
        organization_id=org.id, canonical_url="https://example.com/", hostname="example.com", display_name="Example"
    )
    db_session.add(website)
    db_session.flush()
    now = datetime.now(timezone.utc)
    page = Page(
        website_id=website.id,
        canonical_url="https://example.com/a",
        normalized_url="https://example.com/a",
        first_seen_at=now,
        last_seen_at=now,
    )
    db_session.add(page)
    db_session.flush()
    task = SEOTask(
        website_id=website.id, task_type="set_title", risk_tier=1, proposed_change_json={}, idempotency_key=uuid.uuid4().hex
    )
    db_session.add(task)
    db_session.flush()
    change = ChangeRecord(
        website_id=website.id,
        page_id=page.id,
        seo_task_id=task.id,
        connector_type=ConnectorType.wordpress,
        before_state_json={"title": "Old"},
        after_state_json={"title": "New"},
        actor_type=list(ChangeActorType)[0],
        executed_at=now - timedelta(days=days_ago),
        validation_status=list(ValidationStatus)[0],
    )
    db_session.add(change)
    db_session.flush()
    return website, page, change


def _observe(db_session, website, page, *, on: date, clicks, impressions, position):
    db_session.add(
        KeywordObservation(
            website_id=website.id, page_id=page.id, query=f"q-{on}", date=on, clicks=clicks, impressions=impressions,
            ctr=0.0, average_position=position,
        )
    )
    db_session.flush()


def test_timeline_compares_equal_windows_before_and_after(db_session):
    website, page, change = _website_with_change(db_session, days_ago=20)
    changed_on = change.executed_at.date()
    _observe(db_session, website, page, on=changed_on - timedelta(days=3), clicks=2, impressions=100, position=12.0)
    _observe(db_session, website, page, on=changed_on + timedelta(days=3), clicks=10, impressions=200, position=8.0)
    _observe(db_session, website, page, on=changed_on - timedelta(days=40), clicks=99, impressions=999, position=1.0)

    entry = build_performance_timeline(db_session, website, window_days=7)["entries"][0]

    assert entry["before"] == {"clicks": 2, "impressions": 100, "ctr": 0.02, "average_position": 12.0}
    assert entry["after"] == {"clicks": 10, "impressions": 200, "ctr": 0.05, "average_position": 8.0}
    assert entry["after_window_complete"] is True
    assert entry["operation"] == "set_title"
    assert entry["page_url"] == "https://example.com/a"


def test_timeline_reports_missing_data_as_none_and_flags_an_unfinished_window(db_session):
    website, _, _ = _website_with_change(db_session, days_ago=2)

    result = build_performance_timeline(db_session, website, window_days=28)

    entry = result["entries"][0]
    assert entry["before"] is None
    assert entry["after"] is None
    assert entry["after_window_complete"] is False
    assert entry["site_ga4_before"] is None
    assert "does not" in result["caveat"]


def test_timeline_rejects_unsupported_windows(db_session):
    website, _, _ = _website_with_change(db_session, days_ago=5)
    with pytest.raises(ValueError):
        build_performance_timeline(db_session, website, window_days=30)


def _register(client, email):
    token = client.post(
        "/api/v1/auth/register", json={"email": email, "password": "correct-horse-battery", "organization_name": "Org"}
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    me = client.get("/api/v1/me", headers=headers).json()
    return headers, me["organizations"][0]["id"], me["user"]["id"]


def test_usage_and_timeline_api(client, db_session):
    headers, org_id, user_id = _register(client, "insights-a@example.com")
    website = Website(
        organization_id=uuid.UUID(org_id), canonical_url="https://example.com/", hostname="example.com", display_name="Ex"
    )
    db_session.add(website)
    db_session.flush()
    db_session.add(
        AgentRun(
            website_id=website.id, agent_type=AgentType.keyword_discovery, model="m", status=AgentRunStatus.succeeded,
            input_tokens=100, output_tokens=50, estimated_cost=0.0123, started_at=datetime.now(timezone.utc),
        )
    )
    db_session.flush()
    base = f"/api/v1/organizations/{org_id}/websites/{website.id}"

    usage = client.get(f"{base}/ai-usage", headers=headers)
    assert usage.status_code == 200
    assert usage.json()["by_agent_type"] == [
        {"agent_type": "keyword_discovery", "runs": 1, "input_tokens": 100, "output_tokens": 50, "estimated_cost_usd": 0.0123}
    ]

    assert client.get(f"{base}/performance-timeline", headers=headers).json()["entries"] == []
    assert client.get(f"{base}/performance-timeline", params={"window_days": 30}, headers=headers).status_code == 400

    assert client.get("/api/v1/admin/ai-usage", headers=headers).status_code == 403
    db_session.get(User, uuid.UUID(user_id)).is_platform_admin = True
    db_session.flush()
    platform = client.get("/api/v1/admin/ai-usage", headers=headers)
    assert platform.status_code == 200
    assert platform.json()["by_website"][0]["website_id"] == str(website.id)

    other_headers, other_org, _ = _register(client, "insights-b@example.com")
    for path in ("ai-usage", "performance-timeline"):
        denied = client.get(f"/api/v1/organizations/{other_org}/websites/{website.id}/{path}", headers=other_headers)
        assert denied.status_code == 404
