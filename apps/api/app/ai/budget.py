"""Per-site daily AI spend ceiling (RP-0607, AI_AGENT_SPECIFICATION.md #7:
"Set per-site daily AI budgets and global kill switch").
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.agent_run import AgentRun


class BudgetExceeded(RuntimeError):
    pass


def today_spend_usd(db: Session, website_id: uuid.UUID) -> float:
    start_of_day = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    total = (
        db.query(func.coalesce(func.sum(AgentRun.estimated_cost), 0.0))
        .filter(AgentRun.website_id == website_id, AgentRun.started_at >= start_of_day)
        .scalar()
    )
    return float(total)


def enforce_daily_budget(db: Session, website_id: uuid.UUID) -> None:
    settings = get_settings()
    spent = today_spend_usd(db, website_id)
    if spent >= settings.ai_daily_budget_usd_per_site:
        raise BudgetExceeded(
            f"Website {website_id} has already spent ${spent:.4f} today, "
            f"at or above the ${settings.ai_daily_budget_usd_per_site:.2f} daily AI budget."
        )
