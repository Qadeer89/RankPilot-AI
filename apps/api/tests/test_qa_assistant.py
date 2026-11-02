import json
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.ai import qa_assistant, runner
from app.models.agent_run import AgentRun, AgentRunStatus
from app.models.change_record import ChangeActorType, ChangeRecord, ValidationStatus
from app.models.organization import Organization
from app.models.seo_task import ApprovalStatus, SEOTask, SEOTaskStatus
from app.models.website import Website


def _make_website_and_change(db_session, validation_status: ValidationStatus):
    org = Organization(name="QA Assistant Org", slug=f"qa-assistant-{uuid.uuid4().hex[:8]}")
    db_session.add(org)
    db_session.flush()

    website = Website(
        organization_id=org.id,
        canonical_url="https://example.com/",
        hostname="example.com",
        display_name="Example",
    )
    db_session.add(website)
    db_session.flush()

    task = SEOTask(
        website_id=website.id,
        task_type="set_title",
        risk_tier=1,
        proposed_change_json={"operation": "set_title", "target_url": "https://example.com/", "value": "New Title"},
        approval_status=ApprovalStatus.not_required,
        status=SEOTaskStatus.completed,
        idempotency_key=uuid.uuid4().hex,
    )
    db_session.add(task)
    db_session.flush()

    change_record = ChangeRecord(
        website_id=website.id,
        page_id=None,
        seo_task_id=task.id,
        connector_type="wordpress",
        before_state_json={"operation": "set_title", "value": "Old Title"},
        after_state_json={"value": "New Title", "validation_evidence": {"expected": "New Title", "actual": "New Title"}},
        actor_type=ChangeActorType.system,
        executed_at=datetime.now(timezone.utc),
        validation_status=validation_status,
    )
    db_session.add(change_record)
    db_session.flush()
    return website, change_record


def _fake_response(payload: dict):
    message = SimpleNamespace(content=json.dumps(payload))
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message)],
        usage=SimpleNamespace(prompt_tokens=20, completion_tokens=10),
    )


class _FakeClient:
    def __init__(self, response):
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=lambda **kwargs: response))


def test_summarize_passed_change(db_session, monkeypatch):
    website, change_record = _make_website_and_change(db_session, ValidationStatus.passed)
    monkeypatch.setattr(
        runner, "get_openai_client", lambda: _FakeClient(_fake_response({"summary": "Title updated and confirmed live."}))
    )

    result = qa_assistant.summarize_change(db_session, website, change_record)
    assert result.validation_status == "passed"
    assert "updated" in result.summary.lower()

    agent_run = db_session.query(AgentRun).filter(AgentRun.website_id == website.id).one()
    assert agent_run.status == AgentRunStatus.succeeded


def test_summarize_failed_change_rejects_success_language(db_session, monkeypatch):
    website, change_record = _make_website_and_change(db_session, ValidationStatus.failed)
    monkeypatch.setattr(
        runner,
        "get_openai_client",
        lambda: _FakeClient(_fake_response({"summary": "The title was updated successfully."})),
    )

    with pytest.raises(ValueError):
        qa_assistant.summarize_change(db_session, website, change_record)

    agent_run = db_session.query(AgentRun).filter(AgentRun.website_id == website.id).one()
    assert agent_run.status == AgentRunStatus.failed


def test_summarize_failed_change_accepts_honest_summary(db_session, monkeypatch):
    website, change_record = _make_website_and_change(db_session, ValidationStatus.failed)
    monkeypatch.setattr(
        runner,
        "get_openai_client",
        lambda: _FakeClient(
            _fake_response({"summary": "The title change did not validate; the page still shows the old title."})
        ),
    )

    result = qa_assistant.summarize_change(db_session, website, change_record)
    assert result.validation_status == "failed"
