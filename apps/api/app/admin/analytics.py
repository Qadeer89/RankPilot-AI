"""Super Admin analytics. Every number is computed from database rows; nothing is estimated unless the
field name says so. Definitions (also shown in the dashboard):

  gross collected  sum of paid payments (incl. later-refunded) whose paid_at is in the range
  refunds          sum of refunded_cents whose refunded_at is in the range
  net              gross collected - refunds
  MRR              point-in-time (now): monthly subscriptions at their monthly price + annual at price/12,
                   for provider-billed subscriptions in `active` or `past_due`. Trials, cancelled,
                   expired, refunded and complimentary subscriptions contribute 0.
  ARR              MRR x 12
  trial conversion converted / (converted + cancelled + expired) among trials that STARTED in the range
                   and have finished; still-running trials are reported separately

Cash collected is never added to MRR/ARR. Currencies are never mixed: money is grouped per currency."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.agent_run import AgentRun, AgentRunStatus
from app.models.billing import (
    BillingEvent, BillingEventStatus, BillingInterval, Payment, PaymentStatus, ProjectReplacement, Subscription,
    SubscriptionProvider, SubscriptionStatus, TrialHistory,
)
from app.models.user import User, UserStatus
from app.models.website import Website, WebsiteStatus

PRESETS = ("today", "7d", "30d", "90d", "this_month", "last_month", "custom")
COLLECTED = (PaymentStatus.paid, PaymentStatus.partially_refunded, PaymentStatus.refunded)


class RangeError(ValueError):
    pass


def _day_start(d: date) -> datetime:
    return datetime.combine(d, time.min, tzinfo=timezone.utc)


def resolve_range(preset: str = "30d", start: date | None = None, end: date | None = None, *, now: datetime | None = None):
    """(start, end_exclusive, label) in UTC."""
    now = now or datetime.now(timezone.utc)
    today = now.date()
    if preset == "today":
        s, e = today, today + timedelta(days=1)
    elif preset in ("7d", "30d", "90d"):
        days = int(preset[:-1])
        s, e = today - timedelta(days=days - 1), today + timedelta(days=1)
    elif preset == "this_month":
        s = today.replace(day=1)
        e = (s + timedelta(days=32)).replace(day=1)
    elif preset == "last_month":
        e = today.replace(day=1)
        s = (e - timedelta(days=1)).replace(day=1)
    elif preset == "custom":
        if start is None or end is None:
            raise RangeError("A custom range needs a start and an end date.")
        if end < start:
            raise RangeError("The end date is before the start date.")
        if (end - start).days > 800:
            raise RangeError("The range is too long (limit about 2 years).")
        s, e = start, end + timedelta(days=1)
    else:
        raise RangeError(f"Unknown range '{preset}'. Use one of: {', '.join(PRESETS)}.")
    return _day_start(s), _day_start(e), preset


def _money(rows) -> dict[str, int]:
    return {cur: int(total or 0) for cur, total in rows}


def monthly_equivalent_cents(sub: Subscription) -> int:
    return sub.price_cents if sub.billing_interval == BillingInterval.month else round(sub.price_cents / 12)


def mrr_by_currency(db: Session) -> dict:
    subs = (
        db.query(Subscription)
        .filter(Subscription.provider == SubscriptionProvider.lemonsqueezy,
                Subscription.status.in_([SubscriptionStatus.active, SubscriptionStatus.past_due]))
        .all()
    )
    mrr: dict[str, int] = defaultdict(int)
    at_risk: dict[str, int] = defaultdict(int)
    for sub in subs:
        value = monthly_equivalent_cents(sub)
        mrr[sub.currency] += value
        if sub.status == SubscriptionStatus.past_due:
            at_risk[sub.currency] += value
    return {"mrr_cents": dict(mrr), "arr_cents": {c: v * 12 for c, v in mrr.items()}, "past_due_mrr_cents": dict(at_risk),
            "paying_subscriptions": len(subs)}


def _payments(db: Session, include_test: bool):
    q = db.query(Payment)
    return q if include_test else q.filter(Payment.test_mode.is_(False))


def revenue(db: Session, start: datetime, end: datetime, *, include_test: bool = False) -> dict:
    base = _payments(db, include_test)
    collected = base.filter(Payment.status.in_(COLLECTED), Payment.paid_at >= start, Payment.paid_at < end)
    gross = _money(collected.with_entities(Payment.currency, func.sum(Payment.amount_cents)).group_by(Payment.currency))
    refunds = _money(base.filter(Payment.refunded_at >= start, Payment.refunded_at < end)
                     .with_entities(Payment.currency, func.sum(Payment.refunded_cents)).group_by(Payment.currency))
    currencies = sorted(set(gross) | set(refunds))
    net = {c: gross.get(c, 0) - refunds.get(c, 0) for c in currencies}
    new_sub = _money(collected.filter(Payment.billing_reason == "initial")
                     .with_entities(Payment.currency, func.sum(Payment.amount_cents)).group_by(Payment.currency))
    by_interval: dict[str, dict[str, int]] = defaultdict(dict)
    for interval, cur, total in collected.with_entities(Payment.billing_interval, Payment.currency, func.sum(Payment.amount_cents)).group_by(Payment.billing_interval, Payment.currency):
        by_interval[interval or "unknown"][cur] = int(total or 0)
    failed = base.filter(Payment.status == PaymentStatus.failed, Payment.created_at >= start, Payment.created_at < end)
    failed_count = failed.count()
    failed_amount = _money(failed.with_entities(Payment.currency, func.sum(Payment.amount_cents)).group_by(Payment.currency))
    recovered = (
        db.query(BillingEvent)
        .filter(BillingEvent.event_name == "subscription_payment_recovered", BillingEvent.status == BillingEventStatus.processed,
                BillingEvent.created_at >= start, BillingEvent.created_at < end)
        .count()
    )

    daily: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for paid_at, cur, amount in collected.with_entities(Payment.paid_at, Payment.currency, Payment.amount_cents):
        daily[paid_at.date().isoformat()][cur] += amount
    series = [{"date": (start.date() + timedelta(days=i)).isoformat()} for i in range((end - start).days)]
    for point in series:
        point["collected_cents"] = dict(daily.get(point["date"], {}))

    return {
        "gross_collected_cents": gross, "refunds_cents": refunds, "net_cents": net, "new_subscription_revenue_cents": new_sub,
        "by_interval_cents": dict(by_interval), "failed_payments": {"count": failed_count, "amount_cents": failed_amount},
        "recovered_payments": recovered, "churn": churn(db, start, end), "series": series,
        "recurring": mrr_by_currency(db), "include_test": include_test,
    }


def churn(db: Session, start: datetime, end: datetime) -> dict:
    """Paying subscriptions (at least one collected, non-zero payment) that cancelled in the range, over the
    paying subscriptions that existed at the start of it."""
    paying_ids = {sid for (sid,) in db.query(Payment.subscription_id).filter(Payment.status.in_(COLLECTED), Payment.amount_cents > 0, Payment.subscription_id.isnot(None)).distinct()}
    if not paying_ids:
        return {"cancelled": 0, "base": 0, "rate": None}
    subs = db.query(Subscription).filter(Subscription.id.in_(paying_ids), Subscription.provider == SubscriptionProvider.lemonsqueezy).all()
    base = [s for s in subs if s.created_at < start and (s.cancelled_at is None or s.cancelled_at >= start)]
    cancelled = [s for s in subs if s.cancelled_at is not None and start <= s.cancelled_at < end]
    rate = round(len([s for s in cancelled if s in base]) / len(base), 4) if base else None
    return {"cancelled": len(cancelled), "base": len(base), "rate": rate}


def trials(db: Session, start: datetime, end: datetime) -> dict:
    rows = db.query(TrialHistory).filter(TrialHistory.started_at >= start, TrialHistory.started_at < end).all()
    counts = defaultdict(int)
    for row in rows:
        counts[row.outcome] += 1
    finished = counts["converted"] + counts["cancelled"] + counts["expired"]
    now = datetime.now(timezone.utc)
    soon = (
        db.query(Subscription)
        .filter(Subscription.status == SubscriptionStatus.trialing, Subscription.trial_ends_at.isnot(None),
                Subscription.trial_ends_at >= now, Subscription.trial_ends_at < now + timedelta(days=3))
        .count()
    )
    return {"started": len(rows), "active": counts["active"], "converted": counts["converted"], "cancelled": counts["cancelled"],
            "expired": counts["expired"], "finished": finished,
            "conversion_rate": round(counts["converted"] / finished, 4) if finished else None, "ending_within_3_days": soon}


def replacements(db: Session, start: datetime, end: datetime) -> dict:
    rows = db.query(ProjectReplacement).filter(ProjectReplacement.created_at >= start, ProjectReplacement.created_at < end).all()
    consumed = db.query(Subscription).filter(Subscription.replacements_used >= Subscription.replacement_limit, Subscription.replacement_limit > 0).count()
    return {"total": len(rows), "admin_overrides": sum(1 for r in rows if r.admin_override), "subscriptions_with_allowance_used": consumed,
            "subscriptions_with_exception_granted": db.query(Subscription).filter(Subscription.replacement_limit > 1).count()}


def overview(db: Session, start: datetime, end: datetime, *, include_test: bool = False) -> dict:
    live = Website.status != WebsiteStatus.deleted
    total_projects = db.query(Website).filter(live).count()
    subscribed_ids = {w for (w,) in db.query(Subscription.website_id).filter(Subscription.website_id.isnot(None), Subscription.status.in_(
        [SubscriptionStatus.trialing, SubscriptionStatus.active, SubscriptionStatus.past_due, SubscriptionStatus.cancelled]))}
    by_status = {s.value: n for s, n in db.query(Subscription.status, func.count()).group_by(Subscription.status)}
    by_interval = {i.value: n for i, n in db.query(Subscription.billing_interval, func.count()).filter(
        Subscription.status.in_([SubscriptionStatus.active, SubscriptionStatus.past_due, SubscriptionStatus.trialing])).group_by(Subscription.billing_interval)}
    return {
        "range": {"start": start.isoformat(), "end": end.isoformat()},
        "users": {
            "total": db.query(User).count(),
            "new": db.query(User).filter(User.created_at >= start, User.created_at < end).count(),
            "active": db.query(User).filter(User.status == UserStatus.active).count(),
            "suspended": db.query(User).filter(User.status == UserStatus.disabled).count(),
        },
        "projects": {"total": total_projects, "subscribed": len(subscribed_ids), "unsubscribed": max(total_projects - len(subscribed_ids), 0),
                     "suspended": db.query(Website).filter(Website.status == WebsiteStatus.paused).count()},
        "subscriptions": {"by_status": by_status, "by_interval_live": by_interval, "total": sum(by_status.values()),
                          "complimentary": db.query(Subscription).filter(Subscription.provider == SubscriptionProvider.complimentary,
                                                                         Subscription.status.in_([SubscriptionStatus.active, SubscriptionStatus.trialing])).count()},
        "revenue": {k: v for k, v in revenue(db, start, end, include_test=include_test).items() if k != "series"},
        "trials": trials(db, start, end),
        "replacements": replacements(db, start, end),
    }


def ai_usage(db: Session, start: datetime, end: datetime, *, daily_warning_usd: float) -> dict:
    """`estimated_cost` is computed by RankPilot from token counts and a price table; it is NOT a provider
    invoice. Token counts are exactly what the provider reported."""
    runs = db.query(AgentRun).filter(AgentRun.started_at >= start, AgentRun.started_at < end)
    totals = runs.with_entities(func.count(), func.coalesce(func.sum(AgentRun.input_tokens), 0), func.coalesce(func.sum(AgentRun.output_tokens), 0),
                                func.coalesce(func.sum(AgentRun.estimated_cost), 0.0)).one()
    failed = runs.filter(AgentRun.status == AgentRunStatus.failed).count()
    by_site = (
        runs.join(Website, Website.id == AgentRun.website_id)
        .with_entities(Website.id, Website.display_name, Website.organization_id, func.count(), func.sum(AgentRun.estimated_cost),
                       func.sum(AgentRun.input_tokens + AgentRun.output_tokens))
        .group_by(Website.id, Website.display_name, Website.organization_id).order_by(func.sum(AgentRun.estimated_cost).desc()).limit(50).all()
    )
    by_model = runs.with_entities(AgentRun.model, func.count(), func.sum(AgentRun.estimated_cost)).group_by(AgentRun.model).all()
    daily: dict[str, float] = defaultdict(float)
    for started, cost in runs.with_entities(AgentRun.started_at, AgentRun.estimated_cost):
        daily[started.date().isoformat()] += cost or 0.0
    return {
        "cost_basis": "estimated", "runs": totals[0], "failed_runs": failed, "input_tokens": int(totals[1]), "output_tokens": int(totals[2]),
        "estimated_cost_usd": round(float(totals[3]), 4),
        "by_project": [{"website_id": str(i), "name": n, "organization_id": str(o), "runs": c, "estimated_cost_usd": round(float(cost or 0), 4), "tokens": int(t or 0)} for i, n, o, c, cost, t in by_site],
        "by_model": [{"model": m, "runs": c, "estimated_cost_usd": round(float(cost or 0), 4)} for m, c, cost in by_model],
        "daily": [{"date": d, "estimated_cost_usd": round(v, 4), "over_threshold": v > daily_warning_usd} for d, v in sorted(daily.items())],
        "daily_warning_usd": daily_warning_usd,
    }
