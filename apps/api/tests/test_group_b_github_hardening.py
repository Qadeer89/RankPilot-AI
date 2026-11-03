"""Group B of the custom-website-write addendum (CW-012/013/014): GitHub
connector protected-path denylist, CI status gating validation, and
post-deploy live-URL verification. Builds on the same fixtures as
test_execution_service_generic_connectors.py.
"""

import base64
import uuid

import pytest

from app.ai.schemas import OpportunityProposal
from app.connectors import github_pr
from app.crawler.fetch import FetchError, FetchResult
from app.execution import connections as conn
from app.execution import service as execution_service
from app.execution.service import ExecutionBlocked
from app.models.change_record import ValidationStatus
from app.models.organization import Organization
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
    user = User(email=f"group-b-{uuid.uuid4().hex[:8]}@example.com", hashed_password="x")
    db_session.add(user)
    db_session.flush()
    return user


def _make_website_and_opportunity(db_session, automation_policy=None):
    org = Organization(name="Group B Org", slug=f"group-b-{uuid.uuid4().hex[:8]}")
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


def _connect_github(db_session, website, monkeypatch):
    monkeypatch.setattr(github_pr, "verify_credentials", lambda credentials: {"id": 1})
    conn.connect_github(db_session, website, "acme", "marketing-site", "main", "ghp_abc123")


# --- CW-012: protected-path denylist ------------------------------------


def test_is_protected_path_rejects_known_sensitive_files():
    assert github_pr._is_protected_path(".github/workflows/ci.yml")
    assert github_pr._is_protected_path(".env")
    assert github_pr._is_protected_path(".env.production")
    assert github_pr._is_protected_path("package.json")
    assert github_pr._is_protected_path("package-lock.json")
    assert github_pr._is_protected_path("Dockerfile")
    assert github_pr._is_protected_path("requirements.txt")


def test_is_protected_path_allows_ordinary_page_files():
    assert not github_pr._is_protected_path("about.html")
    assert not github_pr._is_protected_path("pages/about.html")
    assert not github_pr._is_protected_path("src/pages/contact.html")


def test_apply_change_refuses_to_write_a_protected_path_even_if_somehow_reached(db_session, monkeypatch):
    """Defense in depth (CW-012): apply_change() has its own independent
    guard, not just find_target()'s filtering, in case a target_ref for a
    protected path is ever constructed some other way."""
    website, opportunity = _make_website_and_opportunity(db_session)
    _connect_github(db_session, website, monkeypatch)
    credentials = conn.get_github_credentials(db_session, website)

    target_ref = {"file_path": ".github/workflows/deploy.yml", "sha": "sha1", "content": "<title>X</title>"}

    with pytest.raises(github_pr.UnsupportedOperation, match="protected path"):
        github_pr.apply_change(credentials, target_ref, "set_title", "New Title")


# --- CW-013: CI status gates validation ----------------------------------


def _github_happy_path_mocks(monkeypatch, *, ci_state="success", ci_total_count=1):
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
        if url.endswith("/status"):
            return _FakeResponse(200, {"state": ci_state, "total_count": ci_total_count})
        return _FakeResponse(404, {})

    def fake_post(url, json=None, headers=None, timeout=None):
        if url.endswith("/git/refs"):
            return _FakeResponse(201, {"ref": json["ref"]})
        if url.endswith("/pulls"):
            return _FakeResponse(201, {"number": 7, "html_url": "https://github.com/acme/marketing-site/pull/7"})
        return _FakeResponse(400, {})

    def fake_put(url, json=None, headers=None, timeout=None):
        return _FakeResponse(200, {"commit": {"sha": "new-sha"}})

    monkeypatch.setattr(github_pr.httpx, "get", fake_get)
    monkeypatch.setattr(github_pr.httpx, "post", fake_post)
    monkeypatch.setattr(github_pr.httpx, "put", fake_put)


def test_execute_task_passes_when_ci_succeeds(db_session, monkeypatch):
    website, opportunity = _make_website_and_opportunity(db_session)
    _connect_github(db_session, website, monkeypatch)
    task = execution_service.create_tasks_from_proposal(
        db_session, website, opportunity, _proposal(opportunity.id), requested_by=_make_user(db_session).id
    )[0]
    _github_happy_path_mocks(monkeypatch, ci_state="success")

    change_record = execution_service.execute_task(db_session, website, task)

    assert change_record.validation_status == ValidationStatus.passed
    assert change_record.after_state_json["validation_evidence"]["ci_status"] == "success"
    assert task.status == SEOTaskStatus.completed


def test_execute_task_blocks_promotion_when_ci_reports_failure(db_session, monkeypatch):
    """CW-013: a reported CI failure blocks promotion even though the
    file content itself matches what was proposed."""
    website, opportunity = _make_website_and_opportunity(db_session)
    _connect_github(db_session, website, monkeypatch)
    task = execution_service.create_tasks_from_proposal(
        db_session, website, opportunity, _proposal(opportunity.id), requested_by=_make_user(db_session).id
    )[0]

    closed = {}

    def fake_patch(url, json=None, headers=None, timeout=None):
        closed["url"] = url
        return _FakeResponse(200, {"number": 7, "state": "closed"})

    _github_happy_path_mocks(monkeypatch, ci_state="failure")
    monkeypatch.setattr(github_pr.httpx, "patch", fake_patch)

    change_record = execution_service.execute_task(db_session, website, task)

    assert change_record.validation_status == ValidationStatus.failed
    assert change_record.after_state_json["validation_evidence"]["ci_status"] == "failure"
    assert task.status == SEOTaskStatus.failed
    assert closed["url"].endswith("/pulls/7")  # rollback closed the PR


def test_execute_task_does_not_block_on_pending_or_no_checks(db_session, monkeypatch):
    """CI usually hasn't started by the time this synchronous validation
    call runs right after opening the PR -- "pending"/"no_checks" must
    not be treated the same as a reported failure."""
    website, opportunity = _make_website_and_opportunity(db_session)
    _connect_github(db_session, website, monkeypatch)
    task = execution_service.create_tasks_from_proposal(
        db_session, website, opportunity, _proposal(opportunity.id), requested_by=_make_user(db_session).id
    )[0]
    _github_happy_path_mocks(monkeypatch, ci_total_count=0)  # -> "no_checks"

    change_record = execution_service.execute_task(db_session, website, task)

    assert change_record.validation_status == ValidationStatus.passed
    assert change_record.after_state_json["validation_evidence"]["ci_status"] == "no_checks"


def test_get_combined_status_reports_no_checks_on_a_404(db_session, monkeypatch):
    website, _ = _make_website_and_opportunity(db_session)
    _connect_github(db_session, website, monkeypatch)
    credentials = conn.get_github_credentials(db_session, website)
    monkeypatch.setattr(github_pr.httpx, "get", lambda *a, **k: _FakeResponse(404, {}))

    assert github_pr.get_combined_status(credentials, "some-branch") == "no_checks"


# --- CW-014: post-deploy live verification -------------------------------


def test_verify_github_deployment_confirms_a_live_shipped_change(db_session, monkeypatch):
    website, opportunity = _make_website_and_opportunity(db_session)
    _connect_github(db_session, website, monkeypatch)
    task = execution_service.create_tasks_from_proposal(
        db_session, website, opportunity, _proposal(opportunity.id), requested_by=_make_user(db_session).id
    )[0]
    _github_happy_path_mocks(monkeypatch)
    change_record = execution_service.execute_task(db_session, website, task)
    assert change_record.validation_status == ValidationStatus.passed

    live_html = "<html><head><title>New Title</title></head><body>About</body></html>"
    monkeypatch.setattr(
        execution_service,
        "safe_fetch",
        lambda url, **kwargs: FetchResult(
            final_url=url, status_code=200, headers={}, body=live_html, redirect_chain=[]
        ),
    )

    verification = execution_service.verify_github_deployment(db_session, website, change_record)

    assert verification["verified"] is True
    assert verification["actual"] == "New Title"
    assert change_record.after_state_json["post_deploy_verification"]["verified"] is True


def test_verify_github_deployment_reports_unverified_when_live_site_does_not_match(db_session, monkeypatch):
    """The PR merged, per the human, but the deployed site doesn't
    actually show the change -- e.g. a stale build or a cache. An API
    success response earlier is never proof by itself (addendum §3)."""
    website, opportunity = _make_website_and_opportunity(db_session)
    _connect_github(db_session, website, monkeypatch)
    task = execution_service.create_tasks_from_proposal(
        db_session, website, opportunity, _proposal(opportunity.id), requested_by=_make_user(db_session).id
    )[0]
    _github_happy_path_mocks(monkeypatch)
    change_record = execution_service.execute_task(db_session, website, task)

    stale_live_html = "<html><head><title>Old Title</title></head><body>About</body></html>"
    monkeypatch.setattr(
        execution_service,
        "safe_fetch",
        lambda url, **kwargs: FetchResult(
            final_url=url, status_code=200, headers={}, body=stale_live_html, redirect_chain=[]
        ),
    )

    verification = execution_service.verify_github_deployment(db_session, website, change_record)

    assert verification["verified"] is False
    assert verification["actual"] == "Old Title"
    assert verification["expected"] == "New Title"


def test_verify_github_deployment_handles_an_unreachable_live_url(db_session, monkeypatch):
    website, opportunity = _make_website_and_opportunity(db_session)
    _connect_github(db_session, website, monkeypatch)
    task = execution_service.create_tasks_from_proposal(
        db_session, website, opportunity, _proposal(opportunity.id), requested_by=_make_user(db_session).id
    )[0]
    _github_happy_path_mocks(monkeypatch)
    change_record = execution_service.execute_task(db_session, website, task)

    def raise_fetch_error(url, **kwargs):
        raise FetchError("DNS resolution failed")

    monkeypatch.setattr(execution_service, "safe_fetch", raise_fetch_error)

    verification = execution_service.verify_github_deployment(db_session, website, change_record)

    assert verification["verified"] is False
    assert "DNS resolution failed" in verification["error"]


def test_verify_github_deployment_rejects_a_non_github_change_record(db_session, monkeypatch):
    from app.connectors import shopify

    website, opportunity = _make_website_and_opportunity(db_session)
    monkeypatch.setattr(shopify, "verify_credentials", lambda credentials: {"shop": {}})
    conn.connect_shopify(db_session, website, "shop.myshopify.com", "token")
    task = execution_service.create_tasks_from_proposal(
        db_session, website, opportunity, _proposal(opportunity.id), requested_by=_make_user(db_session).id
    )[0]

    def fake_get(url, params=None, headers=None, timeout=None):
        if "/pages.json" in url:
            return _FakeResponse(200, {"pages": [{"id": 1}]})
        if "/metafields.json" in url:
            return _FakeResponse(200, {"metafields": []})
        return _FakeResponse(200, {})

    def fake_post(url, json=None, headers=None, timeout=None):
        return _FakeResponse(201, {"metafield": {"id": 1, "value": json["metafield"]["value"]}})

    monkeypatch.setattr(shopify.httpx, "get", fake_get)
    monkeypatch.setattr(shopify.httpx, "post", fake_post)
    change_record = execution_service.execute_task(db_session, website, task)
    assert change_record.connector_type == ConnectorType.shopify

    with pytest.raises(ExecutionBlocked, match="only applies to the GitHub connector"):
        execution_service.verify_github_deployment(db_session, website, change_record)
