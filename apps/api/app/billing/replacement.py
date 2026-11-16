"""One-time project replacement (docs/COMMERCIAL_SYSTEM.md).

A subscription can be moved to a different project once in its lifetime (a Super Admin can grant an
exception). The move is one atomic step: the subscription keeps its id, customer, interval, renewal date,
trial dates and payment history; only the project it unlocks changes. It never creates a checkout,
payment, trial or subscription."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.billing import notifications
from app.core.domains import domain_key
from app.billing.checkout import live_subscription
from app.models.audit_event import AuditEvent
from app.models.billing import LIVE_STATUSES, ProjectReplacement, Subscription, TrialHistory
from app.models.user import User
from app.models.website import Website, WebsiteStatus


class ReplacementError(Exception):
    def __init__(self, code: str, message: str, http_status: int = 409) -> None:
        super().__init__(message)
        self.code, self.message, self.http_status = code, message, http_status


@dataclass(frozen=True)
class ReplacementResult:
    replacement: ProjectReplacement
    subscription: Subscription


def replacements_remaining(sub: Subscription) -> int:
    return max(sub.replacement_limit - sub.replacements_used, 0)


def eligible_targets(db: Session, sub: Subscription) -> list[Website]:
    """Projects in the same workspace that could receive this subscription."""
    rows = (
        db.query(Website)
        .filter(Website.organization_id == sub.organization_id, Website.status != WebsiteStatus.deleted, Website.id != sub.website_id)
        .order_by(Website.created_at)
        .all()
    )
    return [w for w in rows if live_subscription(db, w.id) is None]


def replace_project(
    db: Session, *, user: User, subscription_id, target_website_id, organization_id, reason: str | None = None
) -> ReplacementResult:
    # Lock the subscription row: two simultaneous requests are serialized, so the second one sees the
    # allowance already used instead of both passing the check.
    sub = (
        db.query(Subscription)
        .filter(Subscription.id == subscription_id, Subscription.organization_id == organization_id)
        .populate_existing()
        .with_for_update()
        .one_or_none()
    )
    if sub is None:
        raise ReplacementError("subscription_not_found", "That subscription was not found.", 404)
    if sub.status not in LIVE_STATUSES:
        raise ReplacementError("subscription_not_live", "Only a current subscription can be moved to another project.")
    if sub.replacements_used >= sub.replacement_limit:
        raise ReplacementError(
            "replacement_exhausted",
            "This subscription's one-time project replacement has already been used. Contact support if you need an exception.",
        )

    target = db.get(Website, target_website_id)
    if target is None or target.organization_id != sub.organization_id or target.status == WebsiteStatus.deleted:
        # Same message whether it is missing or belongs to someone else: nothing about other tenants leaks.
        raise ReplacementError("target_not_found", "The selected project was not found in your workspace.", 404)
    if target.id == sub.website_id:
        raise ReplacementError("same_project", "The subscription already covers that project.")
    if live_subscription(db, target.id) is not None:
        raise ReplacementError("target_subscribed", "The selected project already has its own subscription.")

    previous_website_id = sub.website_id
    try:
        with db.begin_nested():  # everything below succeeds together or not at all
            sub.website_id = target.id
            sub.replacements_used += 1
            _carry_trial(db, sub, previous_website_id, target.id)
            replacement = ProjectReplacement(
                subscription_id=sub.id, user_id=user.id, from_website_id=previous_website_id, to_website_id=target.id,
                sequence=sub.replacements_used, admin_override=sub.replacements_used > 1, reason=reason,
            )
            db.add(replacement)
            db.add(AuditEvent(
                organization_id=sub.organization_id, actor_user_id=user.id, action="billing.project_replaced",
                resource_type="subscription", resource_id=str(sub.id),
                metadata_json={"from_website_id": str(previous_website_id) if previous_website_id else None,
                               "to_website_id": str(target.id), "sequence": sub.replacements_used,
                               "admin_override": replacement.admin_override, "reason": reason},
            ))
            db.flush()
    except IntegrityError as exc:
        raise ReplacementError("target_subscribed", "The selected project already has its own subscription.") from exc

    notifications.queue(db, "project_replaced", sub)
    if sub.replacements_used >= sub.replacement_limit:
        notifications.queue(db, "replacement_allowance_consumed", sub)
    return ReplacementResult(replacement, sub)


def _carry_trial(db: Session, sub: Subscription, from_website_id, to_website_id) -> None:
    """The trial belongs to the subscription: moving it must neither restart it nor let the new project claim a fresh one."""
    if from_website_id is None:
        return
    original = db.query(TrialHistory).filter(TrialHistory.website_id == from_website_id, TrialHistory.subscription_id == sub.id).one_or_none()
    if original is None:
        return
    if db.query(TrialHistory).filter(TrialHistory.website_id == to_website_id).first() is None:
        target = db.get(Website, to_website_id)
        db.add(TrialHistory(website_id=to_website_id, organization_id=sub.organization_id, subscription_id=sub.id,
                            domain_key=domain_key(target.hostname) if target else None,
                            started_at=original.started_at, ends_at=original.ends_at, outcome=original.outcome, ended_at=original.ended_at))


def grant_replacement_exception(db: Session, *, admin: User, subscription: Subscription, reason: str) -> Subscription:
    """Super Admin only (the caller enforces that): allow one more replacement. Reason required and audited."""
    if not reason or not reason.strip():
        raise ReplacementError("reason_required", "A reason is required.", 422)
    before = subscription.replacement_limit
    subscription.replacement_limit += 1
    db.add(AuditEvent(
        organization_id=subscription.organization_id, actor_user_id=admin.id, action="billing.replacement_exception_granted",
        resource_type="subscription", resource_id=str(subscription.id),
        metadata_json={"replacement_limit_before": before, "replacement_limit_after": subscription.replacement_limit, "reason": reason.strip()},
    ))
    db.flush()
    return subscription
