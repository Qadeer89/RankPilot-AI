"""CW-017 (custom-website-write addendum): proves execute_task() is
actually serialized against a concurrent execution of the same task,
with real threads and real, separate Postgres connections/sessions --
not mocks. The project's own history is the reason this gets a real
concurrency test rather than trusting the status check alone: an
earlier "looked sufficient" guard around the AI budget reservation
(app/ai/budget.py) turned out to have exactly this kind of race, found
only by testing with genuine concurrent connections.

Uses its own sessions bound directly to the shared `engine` fixture,
not the rollback-wrapped `db_session` fixture, because two independent
Postgres connections need to see the same *committed* row to race over.
"""

import threading
import uuid

from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.ai.schemas import OpportunityProposal
from app.connectors import shopify
from app.execution import connections as conn
from app.execution import service as execution_service
from app.execution.service import ExecutionBlocked
from app.models.change_record import ChangeRecord
from app.models.organization import Organization
from app.models.seo_opportunity import SEOOpportunity
from app.models.seo_task import SEOTask, SEOTaskStatus
from app.models.user import User
from app.models.website import Website


class _FakeResponse:
    def __init__(self, status_code: int, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = str(payload)

    def json(self):
        return self._payload


def test_execute_task_is_serialized_against_concurrent_execution_of_the_same_task(engine, monkeypatch):
    Session = sessionmaker(bind=engine, future=True, autoflush=False)

    setup_session = Session()
    org_id = None
    user_id = None
    try:
        org = Organization(name="Concurrency Org", slug=f"concurrency-{uuid.uuid4().hex[:8]}")
        setup_session.add(org)
        setup_session.flush()
        org_id = org.id

        website = Website(
            organization_id=org.id,
            canonical_url="https://example.com/",
            hostname="example.com",
            display_name="Example",
            automation_policy={"auto_execute_risk_tier_1": True},
        )
        setup_session.add(website)
        setup_session.flush()

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
        setup_session.add(opportunity)
        setup_session.flush()

        user = User(email=f"concurrency-{uuid.uuid4().hex[:8]}@example.com", hashed_password="x")
        setup_session.add(user)
        setup_session.flush()
        user_id = user.id

        monkeypatch.setattr(shopify, "verify_credentials", lambda credentials: {"shop": {}})
        conn.connect_shopify(setup_session, website, "shop.myshopify.com", "token")

        proposal = OpportunityProposal(
            opportunity_id=str(opportunity.id),
            summary="Add a title.",
            evidence=[{"page_url": "https://example.com/about", "finding_code": "TITLE_MISSING"}],
            proposed_actions=[
                {"operation": "set_title", "target_url": "https://example.com/about", "value": "New Title"}
            ],
            risk_tier=1,
            confidence=0.9,
            requires_approval=False,
            validation_plan=["Fetch page", "Verify title"],
        )
        task = execution_service.create_tasks_from_proposal(
            setup_session, website, opportunity, proposal, requested_by=user.id
        )[0]
        task_id, website_id = task.id, website.id
        setup_session.commit()

        # Pre-seed an existing metafield so apply_change() takes the PUT
        # (update) branch rather than POST (create) -- only PUT is mocked
        # below, matching shopify.py's own branching.
        stored_metafield: dict = {"id": 1, "value": "Old Title"}
        state_lock = threading.Lock()

        def fake_get(url, params=None, headers=None, timeout=None):
            if "/pages.json" in url:
                return _FakeResponse(200, {"pages": [{"id": 1}]})
            if "/metafields.json" in url:
                with state_lock:
                    metafields = [dict(stored_metafield)] if stored_metafield else []
                return _FakeResponse(200, {"metafields": metafields})
            return _FakeResponse(200, {})

        def fake_put(url, json=None, headers=None, timeout=None):
            with state_lock:
                stored_metafield["id"] = 1
                stored_metafield["value"] = json["metafield"]["value"]
                result = dict(stored_metafield)
            return _FakeResponse(200, {"metafield": result})

        monkeypatch.setattr(shopify.httpx, "get", fake_get)
        monkeypatch.setattr(shopify.httpx, "put", fake_put)

        results: dict[str, tuple[str, str]] = {}
        start_barrier = threading.Barrier(2)

        def worker(name: str) -> None:
            session = Session()
            try:
                start_barrier.wait(timeout=5)
                w = session.query(Website).filter(Website.id == website_id).one()
                t = session.query(SEOTask).filter(SEOTask.id == task_id).one()
                try:
                    change_record = execution_service.execute_task(session, w, t)
                    session.commit()
                    results[name] = ("ok", str(change_record.id))
                except ExecutionBlocked as exc:
                    session.rollback()
                    results[name] = ("blocked", str(exc))
            finally:
                session.close()

        t1 = threading.Thread(target=worker, args=("t1",))
        t2 = threading.Thread(target=worker, args=("t2",))
        t1.start()
        t2.start()
        t1.join(timeout=15)
        t2.join(timeout=15)

        assert set(results.keys()) == {"t1", "t2"}, f"a worker thread did not finish: {results}"
        outcomes = [results["t1"][0], results["t2"][0]]
        assert outcomes.count("ok") == 1, f"expected exactly one writer to succeed, got {results}"
        assert outcomes.count("blocked") == 1, f"expected exactly one writer to be blocked, got {results}"

        verify_session = Session()
        try:
            final_task = verify_session.query(SEOTask).filter(SEOTask.id == task_id).one()
            assert final_task.status == SEOTaskStatus.completed

            change_record_count = (
                verify_session.query(ChangeRecord).filter(ChangeRecord.seo_task_id == task_id).count()
            )
            assert change_record_count == 1, "exactly one ChangeRecord must exist -- not two writes for one task"
        finally:
            verify_session.close()
    finally:
        setup_session.close()
        cleanup_session = Session()
        try:
            if org_id is not None:
                cleanup_session.execute(text("DELETE FROM organizations WHERE id = :id"), {"id": org_id})
            if user_id is not None:
                cleanup_session.execute(text("DELETE FROM users WHERE id = :id"), {"id": user_id})
            cleanup_session.commit()
        finally:
            cleanup_session.close()
