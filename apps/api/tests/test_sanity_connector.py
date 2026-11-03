"""Group C of the custom-website-write addendum (CW-006/007/008): the
Sanity CMS connector for the Gul'sRehab founder pilot. Same fixtures/
patterns as test_execution_service_generic_connectors.py.
"""

import uuid

import pytest

from app.ai.schemas import OpportunityProposal
from app.connectors import sanity
from app.connectors.errors import UnsupportedOperation
from app.execution import connections as conn
from app.execution import service as execution_service
from app.models.change_record import ValidationStatus
from app.models.organization import Organization
from app.models.rollback_record import RollbackStatus
from app.models.seo_opportunity import SEOOpportunity
from app.models.seo_task import SEOTaskStatus
from app.models.user import User
from app.models.website import Website
from app.models.website_connection import ConnectorType


class _FakeResponse:
    def __init__(self, status_code: int, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = str(payload)

    def json(self):
        return self._payload


def _make_user(db_session):
    user = User(email=f"sanity-{uuid.uuid4().hex[:8]}@example.com", hashed_password="x")
    db_session.add(user)
    db_session.flush()
    return user


def _make_website_and_opportunity(db_session, automation_policy=None):
    org = Organization(name="Sanity Org", slug=f"sanity-{uuid.uuid4().hex[:8]}")
    db_session.add(org)
    db_session.flush()

    website = Website(
        organization_id=org.id,
        canonical_url="https://gulsrehab.com/",
        hostname="gulsrehab.com",
        display_name="Gul's Rehab",
        automation_policy=automation_policy or {"auto_execute_risk_tier_1": True},
    )
    db_session.add(website)
    db_session.flush()

    opportunity = SEOOpportunity(
        website_id=website.id,
        page_id=None,
        category="metadata",
        title="Improve blog SEO title",
        rationale="SEO title is missing on this blog post.",
        impact_estimate=0.8,
        confidence=1.0,
        effort_estimate=0.2,
        risk_tier=1,
    )
    db_session.add(opportunity)
    db_session.flush()
    return website, opportunity


def _proposal(opportunity_id, operation="set_title", target_url="https://gulsrehab.com/blog/frozen-shoulder"):
    return OpportunityProposal(
        opportunity_id=str(opportunity_id),
        summary="Add an SEO title.",
        evidence=[{"page_url": target_url, "finding_code": "TITLE_MISSING"}],
        proposed_actions=[{"operation": operation, "target_url": target_url, "value": "New SEO Title"}],
        risk_tier=1,
        confidence=0.9,
        requires_approval=False,
        validation_plan=["Fetch document", "Verify seoTitle"],
    )


def _connect_sanity(db_session, website, monkeypatch):
    monkeypatch.setattr(sanity, "verify_credentials", lambda credentials: {"ok": True})
    conn.connect_sanity(db_session, website, "6hfrrnn7", "production", "sk-test-token")


def test_connector_capabilities_registered():
    assert execution_service.get_connector_capabilities(ConnectorType.sanity) == {
        "set_title",
        "set_meta_description",
    }


def test_get_connected_content_connector_resolves_sanity(db_session, monkeypatch):
    website, _ = _make_website_and_opportunity(db_session)
    _connect_sanity(db_session, website, monkeypatch)
    assert conn.get_connected_content_connector(db_session, website) == ConnectorType.sanity


def test_execute_task_happy_path_via_sanity(db_session, monkeypatch):
    website, opportunity = _make_website_and_opportunity(db_session)
    _connect_sanity(db_session, website, monkeypatch)
    task = execution_service.create_tasks_from_proposal(
        db_session, website, opportunity, _proposal(opportunity.id), requested_by=_make_user(db_session).id
    )[0]

    document = {"_id": "doc1", "_rev": "rev1", "seoTitle": "Old SEO Title", "seoDescription": "Old desc"}

    def fake_get(url, params=None, headers=None, timeout=None):
        query = params["query"]
        if "slug.current" in query:
            return _FakeResponse(200, {"result": dict(document)})
        if "_id == $id][0].seoTitle" in query:
            return _FakeResponse(200, {"result": document["seoTitle"]})
        return _FakeResponse(200, {"result": None})

    def fake_post(url, json=None, headers=None, timeout=None):
        patch = json["mutations"][0]["patch"]
        assert patch["ifRevisionID"] == "rev1"
        document["seoTitle"] = patch["set"]["seoTitle"]
        document["_rev"] = "rev2"
        return _FakeResponse(200, {"results": [{"id": "doc1"}]})

    monkeypatch.setattr(sanity.httpx, "get", fake_get)
    monkeypatch.setattr(sanity.httpx, "post", fake_post)

    change_record = execution_service.execute_task(db_session, website, task)

    assert change_record.connector_type == ConnectorType.sanity
    assert change_record.validation_status == ValidationStatus.passed
    assert change_record.before_state_json["value"] == "Old SEO Title"
    assert task.status == SEOTaskStatus.completed
    assert document["seoTitle"] == "New SEO Title"


def test_apply_change_raises_on_revision_conflict(db_session, monkeypatch):
    """CW-008: Sanity's own ifRevisionID check is the real
    optimistic-concurrency mechanism for this connector -- prove a 409
    from Sanity surfaces as a clear, catchable error, not a silent
    overwrite or a raw HTTP exception."""
    website, _ = _make_website_and_opportunity(db_session)
    _connect_sanity(db_session, website, monkeypatch)
    credentials = conn.get_sanity_credentials(db_session, website)

    monkeypatch.setattr(sanity.httpx, "post", lambda *a, **k: _FakeResponse(409, {"error": "revision mismatch"}))

    target_ref = {"_id": "doc1", "_rev": "stale-rev", "seoTitle": "Old"}
    with pytest.raises(UnsupportedOperation, match="revision mismatch|changed since"):
        sanity.apply_change(credentials, target_ref, "set_title", "New Title")


def test_execute_task_rolls_back_on_failed_validation_via_sanity(db_session, monkeypatch):
    website, opportunity = _make_website_and_opportunity(db_session)
    _connect_sanity(db_session, website, monkeypatch)
    task = execution_service.create_tasks_from_proposal(
        db_session, website, opportunity, _proposal(opportunity.id), requested_by=_make_user(db_session).id
    )[0]

    document = {"_id": "doc1", "_rev": "rev1", "seoTitle": "Old SEO Title", "seoDescription": "Old desc"}

    def fake_get(url, params=None, headers=None, timeout=None):
        query = params["query"]
        if "slug.current" in query:
            return _FakeResponse(200, {"result": dict(document)})
        # Validation and rollback's current-revision re-read always
        # report the OLD title, as if the write silently failed to stick.
        if "_id == $id][0].seoTitle" in query:
            return _FakeResponse(200, {"result": "Old SEO Title"})
        if "_rev" in query:
            return _FakeResponse(200, {"result": {"_rev": "rev1"}})
        return _FakeResponse(200, {"result": None})

    def fake_post(url, json=None, headers=None, timeout=None):
        return _FakeResponse(200, {"results": [{"id": "doc1"}]})

    monkeypatch.setattr(sanity.httpx, "get", fake_get)
    monkeypatch.setattr(sanity.httpx, "post", fake_post)

    change_record = execution_service.execute_task(db_session, website, task)

    assert change_record.validation_status == ValidationStatus.failed
    assert task.status == SEOTaskStatus.failed

    from app.models.rollback_record import RollbackRecord

    rollback = db_session.query(RollbackRecord).filter(RollbackRecord.change_record_id == change_record.id).one()
    assert rollback.status == RollbackStatus.completed
    assert rollback.rollback_method == "sanity.set_title"


def test_create_tasks_rejects_service_document_operation(db_session, monkeypatch):
    """The real schema (docs/CUSTOM_WEBSITE_WRITE_GAP_ANALYSIS.md §3)
    has no SEO fields on "service" documents at all -- this connector
    must not claim to support changing them."""
    website, opportunity = _make_website_and_opportunity(db_session)
    _connect_sanity(db_session, website, monkeypatch)

    from app.execution.service import ExecutionBlocked

    proposal = _proposal(opportunity.id, operation="set_canonical_url")
    with pytest.raises(ExecutionBlocked, match="not supported"):
        execution_service.create_tasks_from_proposal(
            db_session, website, opportunity, proposal, requested_by=_make_user(db_session).id
        )


def test_dry_run_reads_sanity_without_writing(db_session, monkeypatch):
    website, opportunity = _make_website_and_opportunity(db_session)
    _connect_sanity(db_session, website, monkeypatch)
    task = execution_service.create_tasks_from_proposal(
        db_session, website, opportunity, _proposal(opportunity.id), requested_by=_make_user(db_session).id
    )[0]

    document = {"_id": "doc1", "_rev": "rev1", "seoTitle": "Old SEO Title", "seoDescription": "Old desc"}
    write_calls = []

    monkeypatch.setattr(
        sanity.httpx, "get", lambda url, params=None, headers=None, timeout=None: _FakeResponse(200, {"result": dict(document)})
    )
    monkeypatch.setattr(sanity.httpx, "post", lambda *a, **k: write_calls.append(1))

    diff = execution_service.dry_run_task(db_session, website, task)

    assert diff["before_value"] == "Old SEO Title"
    assert diff["changed"] is True
    assert write_calls == []
