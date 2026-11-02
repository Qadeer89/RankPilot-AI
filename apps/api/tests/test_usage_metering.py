import uuid
from datetime import datetime, timezone

from app.models.agent_run import AgentRun, AgentRunStatus, AgentType
from app.models.organization import Organization
from app.models.website import Website
from app.usage.metering import METRIC_AI_COST_USD, METRIC_AI_PROPOSALS, record_daily_usage


def _make_website(db_session):
    org = Organization(name="Metering Org", slug=f"metering-{uuid.uuid4().hex[:8]}")
    db_session.add(org)
    db_session.flush()

    website = Website(
        organization_id=org.id, canonical_url="https://example.com/", hostname="example.com", display_name="Example"
    )
    db_session.add(website)
    db_session.flush()
    return website


def test_record_daily_usage_sums_agent_run_cost(db_session):
    website = _make_website(db_session)
    now = datetime.now(timezone.utc)

    db_session.add_all(
        [
            AgentRun(
                website_id=website.id,
                agent_type=AgentType.content_optimization,
                model="gpt-4o-mini",
                status=AgentRunStatus.succeeded,
                estimated_cost=0.02,
                started_at=now,
            ),
            AgentRun(
                website_id=website.id,
                agent_type=AgentType.content_optimization,
                model="gpt-4o-mini",
                status=AgentRunStatus.succeeded,
                estimated_cost=0.03,
                started_at=now,
            ),
        ]
    )
    db_session.flush()

    records = record_daily_usage(db_session, website, day=now.date())
    by_metric = {r.metric: r for r in records}

    assert by_metric[METRIC_AI_PROPOSALS].quantity == 2
    assert round(by_metric[METRIC_AI_COST_USD].quantity, 4) == 0.05
    assert round(by_metric[METRIC_AI_COST_USD].estimated_cost, 4) == 0.05


def test_record_daily_usage_is_idempotent_per_day(db_session):
    website = _make_website(db_session)
    today = datetime.now(timezone.utc).date()

    first = record_daily_usage(db_session, website, day=today)
    second = record_daily_usage(db_session, website, day=today)

    assert {r.id for r in first} == {r.id for r in second}
