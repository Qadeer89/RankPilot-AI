"""app.tasks.scheduler.poll_and_merge_github_prs -- the scheduled
follow-up that auto-merges a RankPilot-opened GitHub PR once CI reports
success, but only for a website that explicitly opted in via
config_json["auto_merge_on_ci_success"], and never on failure/pending/
no CI at all.
"""

import json
import uuid
from datetime import datetime, timezone

import pytest

from app.connectors import github_pr as github_pr_module
from app.core.encryption import encrypt_text
from app.models.change_record import ChangeActorType, ChangeRecord, ValidationStatus
from app.models.organization import Organization
from app.models.seo_task import ApprovalStatus, SEOTask, SEOTaskStatus
from app.models.website import VerificationStatus, Website, WebsiteStatus
from app.models.website_connection import ConnectorType, WebsiteConnection, WebsiteConnectionStatus
from app.tasks import scheduler as scheduler_module


def _make_website_with_github(db_session, *, auto_merge: bool, connected: bool = True):
    org = Organization(name="AutoMerge Org", slug=f"am-{uuid.uuid4().hex[:8]}")
    db_session.add(org)
    db_session.flush()

    website = Website(
        organization_id=org.id,
        canonical_url="https://example.com/",
        hostname="example.com",
        display_name="Example",
        verification_status=VerificationStatus.verified,
        status=WebsiteStatus.active,
    )
    db_session.add(website)
    db_session.flush()

    connection = WebsiteConnection(
        website_id=website.id,
        connector_type=ConnectorType.github,
        encrypted_secret_reference=encrypt_text(json.dumps({"access_token": "ghp_abc"})),
        config_json={
            "owner": "acme",
            "repo": "site",
            "base_branch": "main",
            "auto_merge_on_ci_success": auto_merge,
        },
        granted_scopes=["contents:write", "pull_requests:write"],
        status=WebsiteConnectionStatus.connected if connected else WebsiteConnectionStatus.disconnected,
        last_verified_at=datetime.now(timezone.utc),
    )
    db_session.add(connection)
    db_session.flush()
    return website


def _make_change_record(db_session, website, *, pr_number=5, auto_merged_at=None):
    task = SEOTask(
        website_id=website.id,
        task_type="set_meta_description",
        risk_tier=1,
        proposed_change_json={"operation": "set_meta_description", "target_url": website.canonical_url, "value": "x"},
        approval_status=ApprovalStatus.not_required,
        status=SEOTaskStatus.completed,
        idempotency_key=uuid.uuid4().hex,
    )
    db_session.add(task)
    db_session.flush()
    record = ChangeRecord(
        website_id=website.id,
        seo_task_id=task.id,
        connector_type=ConnectorType.github,
        before_state_json={"value": "old"},
        after_state_json={
            "apply_result": {
                "pr_number": pr_number,
                "pr_url": f"https://github.com/acme/site/pull/{pr_number}",
                "branch": "rankpilot/set_meta_description-abc123",
                "file_path": "app/page.tsx",
            }
        },
        actor_type=ChangeActorType.ai,
        executed_at=datetime.now(timezone.utc),
        validation_status=ValidationStatus.passed,
        auto_merged_at=auto_merged_at,
    )
    db_session.add(record)
    db_session.commit()
    return record


def _run_with(db_session, monkeypatch, *, pull_request, ci_status):
    monkeypatch.setattr(scheduler_module, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(db_session, "close", lambda: None)
    monkeypatch.setattr(github_pr_module, "get_pull_request", lambda creds, pr_number: pull_request)
    monkeypatch.setattr(github_pr_module, "get_combined_status", lambda creds, ref: ci_status)
    merge_calls = []
    monkeypatch.setattr(
        github_pr_module, "merge_pull_request", lambda creds, pr_number: merge_calls.append(pr_number) or {"merged": True}
    )
    count = scheduler_module.poll_and_merge_github_prs()
    return count, merge_calls


def test_merges_when_opted_in_and_ci_success(db_session, monkeypatch):
    website = _make_website_with_github(db_session, auto_merge=True)
    record = _make_change_record(db_session, website)

    count, merge_calls = _run_with(
        db_session, monkeypatch, pull_request={"state": "open", "head": {"ref": "rankpilot/x"}}, ci_status="success"
    )

    assert count == 1
    assert merge_calls == [5]
    db_session.refresh(record)
    assert record.auto_merged_at is not None


def test_does_not_merge_when_not_opted_in(db_session, monkeypatch):
    website = _make_website_with_github(db_session, auto_merge=False)
    record = _make_change_record(db_session, website)

    count, merge_calls = _run_with(
        db_session, monkeypatch, pull_request={"state": "open", "head": {"ref": "rankpilot/x"}}, ci_status="success"
    )

    assert count == 0
    assert merge_calls == []
    db_session.refresh(record)
    assert record.auto_merged_at is None


@pytest.mark.parametrize("ci_status", ["failure", "pending", "no_checks"])
def test_does_not_merge_unless_ci_is_a_clean_success(db_session, monkeypatch, ci_status):
    website = _make_website_with_github(db_session, auto_merge=True)
    record = _make_change_record(db_session, website)

    count, merge_calls = _run_with(
        db_session, monkeypatch, pull_request={"state": "open", "head": {"ref": "rankpilot/x"}}, ci_status=ci_status
    )

    assert count == 0
    assert merge_calls == []
    db_session.refresh(record)
    assert record.auto_merged_at is None


def test_skips_already_merged_record(db_session, monkeypatch):
    website = _make_website_with_github(db_session, auto_merge=True)
    _make_change_record(db_session, website, auto_merged_at=datetime.now(timezone.utc))

    count, merge_calls = _run_with(
        db_session, monkeypatch, pull_request={"state": "open", "head": {"ref": "rankpilot/x"}}, ci_status="success"
    )

    assert count == 0
    assert merge_calls == []


def test_marks_already_merged_by_human_without_calling_merge_again(db_session, monkeypatch):
    website = _make_website_with_github(db_session, auto_merge=True)
    record = _make_change_record(db_session, website)

    count, merge_calls = _run_with(
        db_session, monkeypatch, pull_request={"state": "closed", "merged": True}, ci_status="success"
    )

    assert count == 0
    assert merge_calls == []
    db_session.refresh(record)
    assert record.auto_merged_at is not None


def test_closed_without_merge_is_left_alone(db_session, monkeypatch):
    website = _make_website_with_github(db_session, auto_merge=True)
    record = _make_change_record(db_session, website)

    count, merge_calls = _run_with(
        db_session, monkeypatch, pull_request={"state": "closed", "merged": False}, ci_status="success"
    )

    assert count == 0
    assert merge_calls == []
    db_session.refresh(record)
    assert record.auto_merged_at is None


def test_does_not_merge_when_connector_disconnected(db_session, monkeypatch):
    website = _make_website_with_github(db_session, auto_merge=True, connected=False)
    record = _make_change_record(db_session, website)

    count, merge_calls = _run_with(
        db_session, monkeypatch, pull_request={"state": "open", "head": {"ref": "rankpilot/x"}}, ci_status="success"
    )

    assert count == 0
    assert merge_calls == []
    db_session.refresh(record)
    assert record.auto_merged_at is None


def test_ignores_non_github_connector_types(db_session, monkeypatch):
    website = _make_website_with_github(db_session, auto_merge=True)
    task = SEOTask(
        website_id=website.id,
        task_type="set_title",
        risk_tier=1,
        proposed_change_json={"operation": "set_title", "target_url": website.canonical_url, "value": "x"},
        approval_status=ApprovalStatus.not_required,
        status=SEOTaskStatus.completed,
        idempotency_key=uuid.uuid4().hex,
    )
    db_session.add(task)
    db_session.flush()
    wp_record = ChangeRecord(
        website_id=website.id,
        seo_task_id=task.id,
        connector_type=ConnectorType.wordpress,
        before_state_json={"value": "old"},
        after_state_json={"value": "new"},
        actor_type=ChangeActorType.ai,
        executed_at=datetime.now(timezone.utc),
        validation_status=ValidationStatus.passed,
    )
    db_session.add(wp_record)
    db_session.commit()

    monkeypatch.setattr(scheduler_module, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(db_session, "close", lambda: None)
    merge_calls = []
    monkeypatch.setattr(
        github_pr_module, "merge_pull_request", lambda creds, pr_number: merge_calls.append(pr_number)
    )

    count = scheduler_module.poll_and_merge_github_prs()

    assert count == 0
    assert merge_calls == []
