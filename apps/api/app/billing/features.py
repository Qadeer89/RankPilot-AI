"""Plan-level feature entitlements and limits (the catalogue side of billing).

`entitlement.py` answers "does this project have a paid subscription at all?". This module answers the second question:
"does the plan it is on include this feature, and is it within the plan's limits?".

Rules that keep this safe to switch on later:
  * Nothing here restricts anything unless a plan explicitly says so: a missing feature key means "not restricted by this plan",
    a missing limit means "unlimited". A project on no catalogue plan (for example a Lemon Squeezy or complimentary one) is never
    restricted by this module.
  * It is consulted only in enforcement mode `enforce` (see entitlement.check), so merging this changes no behaviour while
    billing enforcement is off or in `log` mode.
  * Customer data is never deleted by any of these checks. They only decline new paid work.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models.billing import LIVE_STATUSES, BillingPlan, Subscription, SubscriptionProvider
from app.models.website import Website, WebsiteStatus

# Features that exist in the application today, with the name used in plan configuration. Add a key here only when the feature
# really exists; the admin UI offers exactly this list.
FEATURES: dict[str, str] = {
    "crawl": "Website crawling (manual and scheduled)",
    "technical_seo": "Technical SEO analysis",
    "on_page_seo": "On-page SEO analysis",
    "keyword_discovery": "Keyword and topic discovery",
    "keyword_data": "Search Console keyword data and opportunities",
    "competitor_analysis": "Competitor analysis",
    "backlink_verification": "Backlink verification",
    "ai_recommendations": "AI-powered SEO recommendations",
    "content_analysis": "Content intelligence",
    "reports": "SEO reports",
    "history": "SEO history and progress snapshots",
    "gsc_integration": "Google Search Console integration and sync",
    "ga4_integration": "Google Analytics integration and sync",
    "cms_integrations": "Applying changes through CMS connectors",
    "ai_search": "AI search opportunities",
}

# Usage limits that exist (or can be measured) today. A plan sets any of them in `limits_json`; unset means unlimited.
USAGE_LIMITS: dict[str, str] = {
    "crawl_urls_per_project": "Pages crawled per project",
    "crawls_per_month": "Crawls per project per month",
    "competitor_domains": "Competitor domains per project",
    "ai_requests_per_month": "AI requests per project per month",
    "reports_per_month": "Reports per project per month",
    "history_retention_days": "Days of history kept",
}

# Names callers already pass to entitlement.check(), mapped to the feature key plans use.
ALIASES = {
    "ai": "ai_recommendations", "scheduled_crawl": "crawl", "scheduled_sync": "keyword_data", "report": "reports", "execute": "cms_integrations",
}


@dataclass(frozen=True)
class Capacity:
    limit: int | None
    used: int

    @property
    def reached(self) -> bool:
        return self.limit is not None and self.used >= self.limit


def canonical(feature: str) -> str:
    return ALIASES.get(feature, feature)


def plan_for_website(db: Session, website: Website) -> BillingPlan | None:
    """The catalogue plan of the project's live subscription, if it has one."""
    sub = (
        db.query(Subscription)
        .filter(Subscription.website_id == website.id, Subscription.status.in_(LIVE_STATUSES), Subscription.plan_id.isnot(None))
        .first()
    )
    return db.get(BillingPlan, sub.plan_id) if sub is not None else None


def feature_blocked(db: Session, website: Website, feature: str) -> bool:
    """True only when the project's plan explicitly switches the feature off."""
    plan = plan_for_website(db, website)
    if plan is None:
        return False
    return (plan.entitlements_json or {}).get(canonical(feature)) is False


def usage_limit(db: Session, website: Website, key: str) -> int | None:
    plan = plan_for_website(db, website)
    value = (plan.limits_json or {}).get(key) if plan is not None else None
    return int(value) if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def within_usage_limit(db: Session, website: Website, key: str, used: int) -> bool:
    limit = usage_limit(db, website, key)
    return limit is None or used < limit


def project_capacity(db: Session, organization_id) -> Capacity:
    """How many projects the workspace may have, from the plans of its live Paddle subscriptions. No plan sets a limit => unlimited.
    Interim rule while the pricing strategy is open: the highest limit any live plan grants (a plan's `max_websites`, if lower,
    caps its `max_projects`)."""
    used = db.query(Website).filter(Website.organization_id == organization_id, Website.status != WebsiteStatus.deleted).count()
    plans = (
        db.query(BillingPlan)
        .join(Subscription, Subscription.plan_id == BillingPlan.id)
        .filter(Subscription.organization_id == organization_id, Subscription.provider == SubscriptionProvider.paddle, Subscription.status.in_(LIVE_STATUSES))
        .all()
    )
    limits = []
    for p in plans:
        caps = [c for c in (p.max_projects, p.max_websites) if c is not None]
        if caps:
            limits.append(min(caps))
    return Capacity(limit=max(limits) if limits else None, used=used)
