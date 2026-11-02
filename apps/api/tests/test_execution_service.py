import uuid

import pytest

from app.ai.schemas import OpportunityProposal
from app.connectors import wordpress as wp
from app.execution import connections as wp_connections
from app.execution import service as execution_service
from app.models.change_record import ValidationStatus
from app.models.organization import Organization
from app.models.rollback_record import RollbackStatus
from app.models.seo_opportunity import SEOOpportunity
from app.models.seo_task import ApprovalStatus, SEOTaskStatus
from app.models.user import User
from app.models.website import Website, WebsiteStatus


class _FakeResponse:
    def __init__(self, status_code: int, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = str(payload)

    def json(self):
        return self._payload


def _make_user(db_session):
    user = User(email=f"exec-{uuid.uuid4().hex[:8]}@example.com", hashed_password="x")
    db_session.add(user)
    db_session.flush()
    return user


def _make_website_and_opportunity(db_session, automation_policy=None):
    org = Organization(name="Execution Org", slug=f"exec-{uuid.uuid4().hex[:8]}")
    db_session.add(org)
    db_session.flush()

    website = Website(
        organization_id=org.id,
        canonical_url="https://example.com/",
        hostname="example.com",
        display_name="Example",
        automation_policy=automation_policy or {},
    )
    db_session.add(website)
    db_session.flush()

    opportunity = SEOOpportunity(
        website_id=website.id,
        page_id=None,
        category="metadata",
        title="Add a missing page title",
        rationale="This page has no <title>.",
        impact_estimate=0.8,
        confidence=1.0,
        effort_estimate=0.2,
        risk_tier=1,
    )
    db_session.add(opportunity)
    db_session.flush()
    return website, opportunity


def _proposal(opportunity_id, risk_tier=1, target_url="https://example.com/"):
    return OpportunityProposal(
        opportunity_id=str(opportunity_id),
        summary="Add a title.",
        evidence=[{"page_url": target_url, "finding_code": "TITLE_MISSING"}],
        proposed_actions=[{"operation": "set_title", "target_url": target_url, "value": "New Title"}],
        risk_tier=risk_tier,
        confidence=0.9,
        requires_approval=risk_tier >= 2,
        validation_plan=["Fetch page", "Verify title"],
    )


def _connect_wordpress(db_session, website, monkeypatch):
    monkeypatch.setattr(wp.httpx, "get", lambda *a, **k: _FakeResponse(200, {"id": 1}))
    wp_connections.connect_wordpress(db_session, website, "rankpilot", "app-pass-123")


def test_create_tasks_requires_approval_by_default(db_session):
    website, opportunity = _make_website_and_opportunity(db_session)
    tasks = execution_service.create_tasks_from_proposal(
        db_session, website, opportunity, _proposal(opportunity.id), requested_by=_make_user(db_session).id
    )
    assert len(tasks) == 1
    assert tasks[0].approval_status == ApprovalStatus.pending


def test_create_tasks_auto_executes_when_policy_enabled(db_session):
    website, opportunity = _make_website_and_opportunity(
        db_session, automation_policy={"auto_execute_risk_tier_1": True}
    )
    tasks = execution_service.create_tasks_from_proposal(
        db_session, website, opportunity, _proposal(opportunity.id), requested_by=_make_user(db_session).id
    )
    assert tasks[0].approval_status == ApprovalStatus.not_required


def test_create_tasks_blocks_risk_tier_3(db_session):
    website, opportunity = _make_website_and_opportunity(db_session)
    with pytest.raises(execution_service.ExecutionBlocked):
        execution_service.create_tasks_from_proposal(
            db_session, website, opportunity, _proposal(opportunity.id, risk_tier=3), requested_by=_make_user(db_session).id
        )


def test_create_tasks_is_idempotent(db_session):
    website, opportunity = _make_website_and_opportunity(db_session)
    requester = _make_user(db_session).id
    proposal = _proposal(opportunity.id)
    first = execution_service.create_tasks_from_proposal(db_session, website, opportunity, proposal, requested_by=requester)
    second = execution_service.create_tasks_from_proposal(db_session, website, opportunity, proposal, requested_by=requester)
    assert first[0].id == second[0].id


def test_execute_task_blocked_while_approval_pending(db_session):
    website, opportunity = _make_website_and_opportunity(db_session)
    task = execution_service.create_tasks_from_proposal(
        db_session, website, opportunity, _proposal(opportunity.id), requested_by=_make_user(db_session).id
    )[0]
    with pytest.raises(execution_service.ExecutionBlocked):
        execution_service.execute_task(db_session, website, task)


def test_execute_task_blocked_when_website_paused(db_session, monkeypatch):
    website, opportunity = _make_website_and_opportunity(
        db_session, automation_policy={"auto_execute_risk_tier_1": True}
    )
    _connect_wordpress(db_session, website, monkeypatch)
    task = execution_service.create_tasks_from_proposal(
        db_session, website, opportunity, _proposal(opportunity.id), requested_by=_make_user(db_session).id
    )[0]
    website.status = WebsiteStatus.paused
    db_session.flush()

    with pytest.raises(execution_service.ExecutionBlocked):
        execution_service.execute_task(db_session, website, task)


def test_execute_task_happy_path_creates_passing_change_record(db_session, monkeypatch):
    website, opportunity = _make_website_and_opportunity(
        db_session, automation_policy={"auto_execute_risk_tier_1": True}
    )
    _connect_wordpress(db_session, website, monkeypatch)
    task = execution_service.create_tasks_from_proposal(
        db_session, website, opportunity, _proposal(opportunity.id), requested_by=_make_user(db_session).id
    )[0]

    def fake_get(url, params=None, auth=None, timeout=None):
        if "/pages" in url and params:
            return _FakeResponse(200, [{"id": 7}])
        return _FakeResponse(200, {"id": 7, "title": {"rendered": "New Title"}})

    def fake_post(url, auth=None, json=None, timeout=None):
        return _FakeResponse(200, {"id": 7, "title": {"rendered": json["title"]}})

    monkeypatch.setattr(wp.httpx, "get", fake_get)
    monkeypatch.setattr(wp.httpx, "post", fake_post)

    change_record = execution_service.execute_task(db_session, website, task)

    assert change_record.validation_status == ValidationStatus.passed
    assert task.status == SEOTaskStatus.completed
    assert change_record.before_state_json["value"] == "New Title"  # fake_get always returns this title


def test_execute_task_rolls_back_on_failed_validation(db_session, monkeypatch):
    website, opportunity = _make_website_and_opportunity(
        db_session, automation_policy={"auto_execute_risk_tier_1": True}
    )
    _connect_wordpress(db_session, website, monkeypatch)
    task = execution_service.create_tasks_from_proposal(
        db_session, website, opportunity, _proposal(opportunity.id), requested_by=_make_user(db_session).id
    )[0]

    def fake_get(url, params=None, auth=None, timeout=None):
        if "/pages" in url and params:
            return _FakeResponse(200, [{"id": 7}])
        # Validation re-fetch always reports the OLD title, as if the
        # write silently failed to stick.
        return _FakeResponse(200, {"id": 7, "title": {"rendered": "Old Title"}})

    def fake_post(url, auth=None, json=None, timeout=None):
        return _FakeResponse(200, {"id": 7, "title": {"rendered": "Old Title"}})

    monkeypatch.setattr(wp.httpx, "get", fake_get)
    monkeypatch.setattr(wp.httpx, "post", fake_post)

    change_record = execution_service.execute_task(db_session, website, task)

    assert change_record.validation_status == ValidationStatus.failed
    assert task.status == SEOTaskStatus.failed

    from app.models.rollback_record import RollbackRecord

    rollback = db_session.query(RollbackRecord).filter(RollbackRecord.change_record_id == change_record.id).one()
    assert rollback.status == RollbackStatus.completed
