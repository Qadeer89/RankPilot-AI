"""Group A of the custom-website-write addendum (CW-001/003/004/008/009):
connector capability registry, dry-run, stale-revision conflict
detection, the write-specific kill switch, and category-based tier-1
approval opt-in. Builds on the same fixtures/patterns as
test_execution_service_generic_connectors.py.
"""

import uuid

import pytest

from app.ai.schemas import OpportunityProposal
from app.connectors import shopify
from app.execution import connections as conn
from app.execution import policy
from app.execution import service as execution_service
from app.execution.service import ExecutionBlocked
from app.models.organization import Organization
from app.models.seo_opportunity import SEOOpportunity
from app.models.seo_task import ApprovalStatus, SEOTaskStatus
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
    user = User(email=f"group-a-{uuid.uuid4().hex[:8]}@example.com", hashed_password="x")
    db_session.add(user)
    db_session.flush()
    return user


def _make_website_and_opportunity(db_session, automation_policy=None):
    org = Organization(name="Group A Org", slug=f"group-a-{uuid.uuid4().hex[:8]}")
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


def _proposal(opportunity_id, operation="set_title", target_url="https://example.com/about", risk_tier=1):
    return OpportunityProposal(
        opportunity_id=str(opportunity_id),
        summary="Change something.",
        evidence=[{"page_url": target_url, "finding_code": "TITLE_MISSING"}],
        proposed_actions=[{"operation": operation, "target_url": target_url, "value": "New Title"}],
        risk_tier=risk_tier,
        confidence=0.9,
        requires_approval=False,
        validation_plan=["Fetch page", "Verify"],
    )


def _connect_shopify(db_session, website, monkeypatch):
    monkeypatch.setattr(shopify, "verify_credentials", lambda credentials: {"shop": {}})
    conn.connect_shopify(db_session, website, "shop.myshopify.com", "token")


def _patch_shopify_happy_path(monkeypatch, current_value="Old Title"):
    stored_metafield = {"id": 1, "value": current_value}

    def fake_get(url, params=None, headers=None, timeout=None):
        if "/pages.json" in url:
            return _FakeResponse(200, {"pages": [{"id": 1}]})
        if "/metafields.json" in url:
            return _FakeResponse(200, {"metafields": [stored_metafield]})
        return _FakeResponse(200, {})

    def fake_put(url, json=None, headers=None, timeout=None):
        stored_metafield["value"] = json["metafield"]["value"]
        return _FakeResponse(200, {"metafield": dict(stored_metafield)})

    monkeypatch.setattr(shopify.httpx, "get", fake_get)
    monkeypatch.setattr(shopify.httpx, "put", fake_put)
    return stored_metafield


# --- CW-001: connector capability registry -----------------------------


def test_get_connector_capabilities_matches_each_connector_module():
    assert execution_service.get_connector_capabilities(ConnectorType.shopify) == shopify.SUPPORTED_OPERATIONS
    assert "set_title" in execution_service.get_connector_capabilities(ConnectorType.wordpress)


def test_create_tasks_rejects_an_operation_the_connected_connector_does_not_support(db_session, monkeypatch):
    website, opportunity = _make_website_and_opportunity(db_session)
    _connect_shopify(db_session, website, monkeypatch)

    proposal = _proposal(opportunity.id, operation="set_canonical_url")

    with pytest.raises(ExecutionBlocked, match="not supported"):
        execution_service.create_tasks_from_proposal(
            db_session, website, opportunity, proposal, requested_by=_make_user(db_session).id
        )


def test_execute_task_rejects_an_unsupported_operation_even_if_a_task_already_exists(db_session, monkeypatch):
    """Defense in depth: even if a task for an unsupported operation
    somehow got created (e.g. the connector was swapped after creation),
    execute_task must still refuse it rather than crash deep inside a
    connector call."""
    website, opportunity = _make_website_and_opportunity(
        db_session, automation_policy={"auto_execute_risk_tier_1": True}
    )
    _connect_shopify(db_session, website, monkeypatch)

    task = execution_service.create_tasks_from_proposal(
        db_session, website, opportunity, _proposal(opportunity.id), requested_by=_make_user(db_session).id
    )[0]
    # Simulate a task that was created before a capability narrowed, or
    # tampered proposed_change_json, by forcing an unsupported operation.
    task.proposed_change_json = {**task.proposed_change_json, "operation": "set_canonical_url"}
    db_session.flush()

    with pytest.raises(ExecutionBlocked, match="not supported"):
        execution_service.execute_task(db_session, website, task)
    assert task.status == SEOTaskStatus.failed


# --- CW-009/CW-008: dry-run + stale-revision conflict detection --------


def test_dry_run_reads_current_value_without_writing(db_session, monkeypatch):
    website, opportunity = _make_website_and_opportunity(db_session)
    _connect_shopify(db_session, website, monkeypatch)
    task = execution_service.create_tasks_from_proposal(
        db_session, website, opportunity, _proposal(opportunity.id), requested_by=_make_user(db_session).id
    )[0]

    write_calls = []
    stored_metafield = _patch_shopify_happy_path(monkeypatch, current_value="Old Title")
    original_put = shopify.httpx.put
    monkeypatch.setattr(shopify.httpx, "put", lambda *a, **k: write_calls.append(1) or original_put(*a, **k))

    diff = execution_service.dry_run_task(db_session, website, task)

    assert diff == {
        "operation": "set_title",
        "target_url": "https://example.com/about",
        "before_value": "Old Title",
        "proposed_value": "New Title",
        "changed": True,
    }
    assert write_calls == []  # apply_change was never reached
    assert stored_metafield["value"] == "Old Title"  # nothing was written
    assert task.proposed_change_json["expected_before_value"] == "Old Title"
    assert task.status == SEOTaskStatus.pending  # dry-run doesn't move task state


def test_execute_task_proceeds_when_value_unchanged_since_dry_run(db_session, monkeypatch):
    website, opportunity = _make_website_and_opportunity(
        db_session, automation_policy={"auto_execute_risk_tier_1": True}
    )
    _connect_shopify(db_session, website, monkeypatch)
    task = execution_service.create_tasks_from_proposal(
        db_session, website, opportunity, _proposal(opportunity.id), requested_by=_make_user(db_session).id
    )[0]
    _patch_shopify_happy_path(monkeypatch, current_value="Old Title")

    execution_service.dry_run_task(db_session, website, task)
    change_record = execution_service.execute_task(db_session, website, task)

    assert task.status == SEOTaskStatus.completed
    assert change_record.before_state_json["value"] == "Old Title"


def test_execute_task_blocks_on_stale_revision_detected_since_dry_run(db_session, monkeypatch):
    """CW-008: someone (or something) changed the title between the
    dry-run and execution -- execution must refuse rather than silently
    overwrite that concurrent edit."""
    website, opportunity = _make_website_and_opportunity(
        db_session, automation_policy={"auto_execute_risk_tier_1": True}
    )
    _connect_shopify(db_session, website, monkeypatch)
    task = execution_service.create_tasks_from_proposal(
        db_session, website, opportunity, _proposal(opportunity.id), requested_by=_make_user(db_session).id
    )[0]
    stored_metafield = _patch_shopify_happy_path(monkeypatch, current_value="Old Title")

    execution_service.dry_run_task(db_session, website, task)
    assert task.proposed_change_json["expected_before_value"] == "Old Title"

    # Someone changed it out-of-band after the dry-run.
    stored_metafield["value"] = "Someone Else's Edit"

    with pytest.raises(ExecutionBlocked, match="Stale revision"):
        execution_service.execute_task(db_session, website, task)

    assert task.status == SEOTaskStatus.failed
    assert stored_metafield["value"] == "Someone Else's Edit"  # execution never wrote over it


def test_execute_task_without_a_prior_dry_run_is_unaffected_by_the_stale_check(db_session, monkeypatch):
    """Dry-run is optional, not mandatory, for Group A -- a task executed
    without ever calling dry_run_task behaves exactly as before."""
    website, opportunity = _make_website_and_opportunity(
        db_session, automation_policy={"auto_execute_risk_tier_1": True}
    )
    _connect_shopify(db_session, website, monkeypatch)
    task = execution_service.create_tasks_from_proposal(
        db_session, website, opportunity, _proposal(opportunity.id), requested_by=_make_user(db_session).id
    )[0]
    _patch_shopify_happy_path(monkeypatch, current_value="Old Title")

    change_record = execution_service.execute_task(db_session, website, task)
    assert task.status == SEOTaskStatus.completed
    assert change_record is not None


# --- CW-004: write-specific kill switch ---------------------------------


def test_execute_task_blocked_when_writes_disabled(db_session, monkeypatch):
    website, opportunity = _make_website_and_opportunity(
        db_session, automation_policy={"auto_execute_risk_tier_1": True}
    )
    _connect_shopify(db_session, website, monkeypatch)
    task = execution_service.create_tasks_from_proposal(
        db_session, website, opportunity, _proposal(opportunity.id), requested_by=_make_user(db_session).id
    )[0]
    _patch_shopify_happy_path(monkeypatch)

    website.writes_enabled = False
    db_session.flush()

    with pytest.raises(ExecutionBlocked, match="kill switch"):
        execution_service.execute_task(db_session, website, task)
    assert task.status == SEOTaskStatus.pending  # never even entered "executing"


def test_dry_run_still_works_when_writes_disabled(db_session, monkeypatch):
    """The kill switch blocks writes, not analysis -- dry-run is
    read-only and must keep working while writes are disabled."""
    website, opportunity = _make_website_and_opportunity(db_session)
    _connect_shopify(db_session, website, monkeypatch)
    task = execution_service.create_tasks_from_proposal(
        db_session, website, opportunity, _proposal(opportunity.id), requested_by=_make_user(db_session).id
    )[0]
    _patch_shopify_happy_path(monkeypatch, current_value="Old Title")

    website.writes_enabled = False
    db_session.flush()

    diff = execution_service.dry_run_task(db_session, website, task)
    assert diff["before_value"] == "Old Title"


def test_website_writes_enabled_defaults_to_true(db_session):
    website, _ = _make_website_and_opportunity(db_session)
    assert website.writes_enabled is True


# --- CW-003: category-based tier-1 approval opt-in ----------------------


def test_requires_approval_tier1_blanket_flag_still_works(db_session):
    website, _ = _make_website_and_opportunity(db_session, automation_policy={"auto_execute_risk_tier_1": True})
    assert policy.requires_approval(website, 1, "set_title") is False


def test_requires_approval_tier1_category_opt_in_without_blanket_flag(db_session):
    website, _ = _make_website_and_opportunity(
        db_session, automation_policy={"auto_execute_categories": {"metadata": True}}
    )
    assert policy.requires_approval(website, 1, "set_title") is False
    assert policy.requires_approval(website, 1, "set_meta_description") is False


def test_requires_approval_tier1_category_opt_in_does_not_cover_other_categories(db_session):
    website, _ = _make_website_and_opportunity(
        db_session, automation_policy={"auto_execute_categories": {"metadata": True}}
    )
    # An operation not in the "metadata" category (or with no category at
    # all) must still require approval -- the opt-in is per category, not
    # a hidden blanket grant.
    assert policy.requires_approval(website, 1, "set_canonical_url") is True


def test_requires_approval_tier1_defaults_to_required_with_no_policy(db_session):
    website, _ = _make_website_and_opportunity(db_session, automation_policy={})
    assert policy.requires_approval(website, 1, "set_title") is True


def test_requires_approval_backward_compatible_without_operation_argument(db_session):
    website, _ = _make_website_and_opportunity(db_session, automation_policy={"auto_execute_risk_tier_1": True})
    assert policy.requires_approval(website, 1) is False


def test_create_tasks_from_proposal_honors_category_opt_in(db_session, monkeypatch):
    website, opportunity = _make_website_and_opportunity(
        db_session, automation_policy={"auto_execute_categories": {"metadata": True}}
    )
    _connect_shopify(db_session, website, monkeypatch)

    task = execution_service.create_tasks_from_proposal(
        db_session, website, opportunity, _proposal(opportunity.id), requested_by=_make_user(db_session).id
    )[0]

    assert task.approval_status == ApprovalStatus.not_required
