"""Per-site and global daily AI spend ceilings, plus a kill switch
(RP-0607, AI_AGENT_SPECIFICATION.md #7: "Set per-site daily AI budgets
and global kill switch"; RP13-012/013).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, text
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


def today_global_spend_usd(db: Session) -> float:
    start_of_day = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    total = (
        db.query(func.coalesce(func.sum(AgentRun.estimated_cost), 0.0))
        .filter(AgentRun.started_at >= start_of_day)
        .scalar()
    )
    return float(total)


def _advisory_lock_key(website_id: uuid.UUID) -> int:
    """Fold a UUID down to the signed 64-bit int Postgres advisory locks
    take. Collisions are harmless here -- a false lock contention just
    means two different websites briefly serialize, not a correctness
    problem.
    """
    unsigned = int.from_bytes(website_id.bytes[:8], "big")
    return unsigned - (1 << 63)  # fold the top half of the uint64 range negative


def _acquire_budget_lock(db: Session, website_id: uuid.UUID) -> None:
    """RP13-013: serialize budget check-then-spend for one website within
    this transaction, so two concurrent AI calls for the same website
    cannot both pass the budget check before either has recorded its
    actual cost. A transaction-scoped advisory lock releases itself
    automatically on commit or rollback -- no separate unlock needed,
    and no risk of leaking a held lock if the caller raises.
    """
    db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _advisory_lock_key(website_id)})


def enforce_daily_budget(db: Session, website_id: uuid.UUID) -> None:
    settings = get_settings()

    if settings.ai_kill_switch_enabled:
        raise BudgetExceeded("AI calls are disabled by the global kill switch (RANKPILOT_AI_KILL_SWITCH_ENABLED).")

    _acquire_budget_lock(db, website_id)

    global_spent = today_global_spend_usd(db)
    if global_spent >= settings.ai_global_daily_budget_usd:
        raise BudgetExceeded(
            f"Global AI spend today (${global_spent:.4f}) is at or above the "
            f"${settings.ai_global_daily_budget_usd:.2f} global daily budget."
        )

    spent = today_spend_usd(db, website_id)
    if spent >= settings.ai_daily_budget_usd_per_site:
        raise BudgetExceeded(
            f"Website {website_id} has already spent ${spent:.4f} today, "
            f"at or above the ${settings.ai_daily_budget_usd_per_site:.2f} daily AI budget."
        )
