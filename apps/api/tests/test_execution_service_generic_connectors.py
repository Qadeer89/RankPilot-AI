"""Execution service dispatch for the generic (non-WordPress) connectors
-- Shopify, Webflow, and GitHub -- added alongside the three new write
connectors (MASTER_SPEC.md #5: "additional CMS write connectors",
"GitHub/deployment integration for custom-code sites").
"""

import base64
import uuid

from app.ai.schemas import OpportunityProposal
from app.connectors import github_pr, shopify, webflow
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
    user = User(email=f"exec-generic-{uuid.uuid4().hex[:8]}@example.com", hashed_password="x")
    db_session.add(user)
    db_session.flush()
    return user


def _make_website_and_opportunity(db_session, automation_policy=None):
    org = Organization(name="Generic Connector Org", slug=f"generic-conn-{uuid.uuid4().hex[:8]}")
    db_session.add(org)
    db_session.flush()

    website = Website(
        organization_id=org.id,
        canonical_url="https://example.com/",
        hostname="example.com",
        display_name="Example",
        automation_policy=automation_policy or {"auto_execute_risk_tier_1": True},
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


def _proposal(opportunity_id, target_url="https://example.com/about"):
    return OpportunityProposal(
        opportunity_id=str(opportunity_id),
        summary="Add a title.",
        evidence=[{"page_url": target_url, "finding_code": "TITLE_MISSING"}],
        proposed_actions=[{"operation": "set_title", "target_url": target_url, "value": "New Title"}],
        risk_tier=1,
        confidence=0.9,
        requires_approval=False,
        validation_plan=["Fetch page", "Verify title"],
    )


def test_get_connected_content_connector_prefers_wordpress_over_others(db_session, monkeypatch):
    website, _ = _make_website_and_opportunity(db_session)
    monkeypatch.setattr(shopify, "verify_credentials", lambda credentials: {"shop": {}})
    conn.connect_shopify(db_session, website, "shop.myshopify.com", "token")

    # connections.py imports verify_credentials by name from wordpress, so
    # the module-qualified attribute must be patched where it's actually
    # looked up: on `conn`, not on `app.connectors.wordpress`.
    monkeypatch.setattr(conn, "verify_credentials", lambda credentials: {"id": 1})
    conn.connect_wordpress(db_session, website, "rankpilot", "app-pass")

    assert conn.get_connected_content_connector(db_session, website) == ConnectorType.wordpress


def test_execute_task_happy_path_via_shopify(db_session, monkeypatch):
    website, opportunity = _make_website_and_opportunity(db_session)
    monkeypatch.setattr(shopify, "verify_credentials", lambda credentials: {"shop": {}})
    conn.connect_shopify(db_session, website, "shop.myshopify.com", "token")

    task = execution_service.create_tasks_from_proposal(
        db_session, website, opportunity, _proposal(opportunity.id), requested_by=_make_user(db_session).id
    )[0]

    stored_metafield = {}

    def fake_get(url, params=None, headers=None, timeout=None):
        if "/pages.json" in url:
            return _FakeResponse(200, {"pages": [{"id": 1}]})
        if "/metafields.json" in url:
            metafields = [stored_metafield] if stored_metafield else []
            return _FakeResponse(200, {"metafields": metafields})
        return _FakeResponse(200, {})

    def fake_post(url, json=None, headers=None, timeout=None):
        stored_metafield["id"] = 1
        stored_metafield["value"] = json["metafield"]["value"]
        return _FakeResponse(201, {"metafield": dict(stored_metafield)})

    monkeypatch.setattr(shopify.httpx, "get", fake_get)
    monkeypatch.setattr(shopify.httpx, "post", fake_post)

    change_record = execution_service.execute_task(db_session, website, task)

    assert change_record.connector_type == ConnectorType.shopify
    assert change_record.validation_status == ValidationStatus.passed
    assert task.status == SEOTaskStatus.completed


def test_execute_task_rolls_back_on_failed_validation_via_webflow(db_session, monkeypatch):
    website, opportunity = _make_website_and_opportunity(db_session)
    monkeypatch.setattr(webflow, "verify_credentials", lambda credentials: {"id": "site1"})
    conn.connect_webflow(db_session, website, "site1", "token")

    task = execution_service.create_tasks_from_proposal(
        db_session, website, opportunity, _proposal(opportunity.id), requested_by=_make_user(db_session).id
    )[0]

    def fake_get(url, params=None, headers=None, timeout=None):
        if url.endswith("/pages"):
            return _FakeResponse(200, {"pages": [{"id": "page1", "slug": "about"}]})
        # Validation re-fetch always reports the OLD title, as if the
        # write silently failed to stick.
        return _FakeResponse(200, {"title": "Old Title"})

    def fake_patch(url, json=None, headers=None, timeout=None):
        return _FakeResponse(200, {"title": "Old Title"})

    monkeypatch.setattr(webflow.httpx, "get", fake_get)
    monkeypatch.setattr(webflow.httpx, "patch", fake_patch)

    change_record = execution_service.execute_task(db_session, website, task)

    assert change_record.validation_status == ValidationStatus.failed
    assert task.status == SEOTaskStatus.failed

    from app.models.rollback_record import RollbackRecord

    rollback = db_session.query(RollbackRecord).filter(RollbackRecord.change_record_id == change_record.id).one()
    assert rollback.status == RollbackStatus.completed
    assert rollback.rollback_method == "webflow.set_title"


def test_execute_task_via_github_opens_pr_and_rollback_closes_it(db_session, monkeypatch):
    website, opportunity = _make_website_and_opportunity(db_session)
    monkeypatch.setattr(github_pr, "verify_credentials", lambda credentials: {"id": 1})
    conn.connect_github(db_session, website, "acme", "marketing-site", "main", "ghp_abc123")

    task = execution_service.create_tasks_from_proposal(
        db_session, website, opportunity, _proposal(opportunity.id, target_url="https://example.com/about"), requested_by=_make_user(db_session).id
    )[0]

    page_html = "<html><head><title>Old Title</title></head><body>About</body></html>"
    new_html = page_html.replace("Old Title", "New Title")

    def fake_get(url, params=None, headers=None, timeout=None):
        if url.endswith("/contents/about.html"):
            if params and params.get("ref") not in (None, "main"):
                return _FakeResponse(200, {"content": base64.b64encode(new_html.encode()).decode()})
            return _FakeResponse(200, {"sha": "sha1", "content": base64.b64encode(page_html.encode()).decode()})
        if url.endswith("/git/ref/heads/main"):
            return _FakeResponse(200, {"object": {"sha": "base-sha"}})
        if "/pulls/" in url:
            return _FakeResponse(200, {"state": "open"})
        return _FakeResponse(404, {})

    def fake_post(url, json=None, headers=None, timeout=None):
        if url.endswith("/git/refs"):
            return _FakeResponse(201, {"ref": json["ref"]})
        if url.endswith("/pulls"):
            return _FakeResponse(201, {"number": 7, "html_url": "https://github.com/acme/marketing-site/pull/7"})
        return _FakeResponse(400, {})

    def fake_put(url, json=None, headers=None, timeout=None):
        return _FakeResponse(200, {"commit": {"sha": "new-sha"}})

    closed = {}

    def fake_patch(url, json=None, headers=None, timeout=None):
        closed["url"] = url
        return _FakeResponse(200, {"number": 7, "state": "closed"})

    monkeypatch.setattr(github_pr.httpx, "get", fake_get)
    monkeypatch.setattr(github_pr.httpx, "post", fake_post)
    monkeypatch.setattr(github_pr.httpx, "put", fake_put)
    monkeypatch.setattr(github_pr.httpx, "patch", fake_patch)

    change_record = execution_service.execute_task(db_session, website, task)

    assert change_record.connector_type == ConnectorType.github
    assert change_record.validation_status == ValidationStatus.passed
    assert change_record.after_state_json["apply_result"]["pr_number"] == 7
    assert task.status == SEOTaskStatus.completed
