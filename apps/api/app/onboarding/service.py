"""Guided Onboarding (Part 2-3 of the onboarding+assistant spec).

Every step's completion is computed live from the organization's real
data on each request -- nothing here is a cached flag that could drift
out of sync with reality. `OnboardingState` only remembers two things
that genuinely can't be derived: which optional steps were explicitly
skipped, and whether the welcome screen was dismissed.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.crawl_job import CrawlJob, CrawlStatus, CrawlTrigger
from app.models.oauth_connection import OAuthConnection, OAuthConnectionStatus, OAuthProvider
from app.models.onboarding_state import OnboardingState
from app.models.seo_finding import SEOFinding
from app.models.seo_task import SEOTask
from app.models.website import VerificationStatus, Website
from app.models.website_connection import WebsiteConnection, WebsiteConnectionStatus

# Step keys that are allowed to be skipped (POST .../onboarding/skip
# rejects anything else -- a mandatory step can't be waved away).
OPTIONAL_STEPS = {"connect_cms", "connect_gsc", "connect_ga4", "ai_optimization", "notifications", "explore_dashboard"}

STEP_DEFINITIONS = [
    {"key": "welcome", "title": "Welcome to RankPilot AI", "mandatory": True},
    {"key": "add_website", "title": "Add your website", "mandatory": True},
    {"key": "verify_website", "title": "Verify website ownership", "mandatory": True},
    {"key": "connect_cms", "title": "Connect your CMS", "mandatory": False},
    {"key": "connect_gsc", "title": "Connect Google Search Console", "mandatory": False},
    {"key": "connect_ga4", "title": "Connect Google Analytics 4", "mandatory": False},
    {"key": "configure_crawling", "title": "Configure website crawling", "mandatory": True},
    {"key": "first_audit", "title": "Run your first SEO audit", "mandatory": True},
    {"key": "review_findings", "title": "Review SEO findings", "mandatory": True},
    {"key": "ai_optimization", "title": "Configure AI optimization", "mandatory": False},
    {"key": "automation_mode", "title": "Choose an automation mode", "mandatory": True},
    {"key": "notifications", "title": "Configure notifications", "mandatory": False},
    {"key": "explore_dashboard", "title": "Explore your dashboard", "mandatory": False},
]


@dataclass
class StepStatus:
    key: str
    title: str
    mandatory: bool
    completed: bool
    skipped: bool
    detail: str


def _get_or_create_state(db: Session, organization_id: uuid.UUID) -> OnboardingState:
    state = db.query(OnboardingState).filter(OnboardingState.organization_id == organization_id).one_or_none()
    if state is None:
        state = OnboardingState(organization_id=organization_id, skipped_steps=[])
        db.add(state)
        db.flush()
    return state


def _compute_step(
    key: str,
    *,
    websites: list[Website],
    website_ids: list[uuid.UUID],
    db: Session,
    state: OnboardingState,
) -> tuple[bool, str]:
    """Returns (completed, detail) for one step key, computed from real
    data -- see module docstring."""
    if key == "welcome":
        completed = state.welcomed_at is not None
        return completed, "Welcome screen dismissed." if completed else "Not started yet."

    if key == "add_website":
        completed = len(websites) > 0
        return completed, f"{len(websites)} website(s) added." if completed else "No website added yet."

    if key == "verify_website":
        verified = [w for w in websites if w.verification_status == VerificationStatus.verified]
        completed = len(verified) > 0
        return completed, (
            f"{len(verified)} of {len(websites)} website(s) verified." if websites else "Add a website first."
        )

    if key == "connect_cms":
        if not website_ids:
            return False, "Add a website first."
        connected = (
            db.query(WebsiteConnection)
            .filter(
                WebsiteConnection.website_id.in_(website_ids),
                WebsiteConnection.status == WebsiteConnectionStatus.connected,
            )
            .count()
        )
        return connected > 0, (
            "A CMS connector is connected." if connected > 0 else "No CMS connected yet (optional)."
        )

    if key == "connect_gsc":
        connected = (
            db.query(OAuthConnection)
            .filter(
                OAuthConnection.organization_id == state.organization_id,
                OAuthConnection.provider == OAuthProvider.google_search_console,
                OAuthConnection.status == OAuthConnectionStatus.connected,
            )
            .count()
        )
        return connected > 0, (
            "Google Search Console is connected." if connected > 0 else "Not connected yet (optional)."
        )

    if key == "connect_ga4":
        connected = (
            db.query(OAuthConnection)
            .filter(
                OAuthConnection.organization_id == state.organization_id,
                OAuthConnection.provider == OAuthProvider.google_analytics,
                OAuthConnection.status == OAuthConnectionStatus.connected,
            )
            .count()
        )
        return connected > 0, "GA4 is connected." if connected > 0 else "Not connected yet (optional)."

    if key == "configure_crawling":
        if not website_ids:
            return False, "Add a website first."
        has_crawl = db.query(CrawlJob).filter(CrawlJob.website_id.in_(website_ids), CrawlJob.trigger != CrawlTrigger.post_change).first() is not None
        return has_crawl, "A crawl has been started." if has_crawl else "No crawl started yet."

    if key == "first_audit":
        if not website_ids:
            return False, "Add a website first."
        completed_crawl = (
            db.query(CrawlJob)
            .filter(
                CrawlJob.website_id.in_(website_ids),
                CrawlJob.status == CrawlStatus.completed,
                CrawlJob.trigger != CrawlTrigger.post_change,
            )
            .first()
            is not None
        )
        return completed_crawl, (
            "First audit completed." if completed_crawl else "No completed audit yet."
        )

    if key == "review_findings":
        if not website_ids:
            return False, "Add a website first."
        has_findings_or_clean_audit = (
            db.query(SEOFinding).filter(SEOFinding.website_id.in_(website_ids)).first() is not None
        )
        completed_crawl = (
            db.query(CrawlJob)
            .filter(
                CrawlJob.website_id.in_(website_ids),
                CrawlJob.status == CrawlStatus.completed,
                CrawlJob.trigger != CrawlTrigger.post_change,
            )
            .first()
            is not None
        )
        completed = has_findings_or_clean_audit or completed_crawl
        return completed, "Findings are available to review." if completed else "Run your first audit first."

    if key == "ai_optimization":
        if not website_ids:
            return False, "Add a website first."
        has_task = db.query(SEOTask).filter(SEOTask.website_id.in_(website_ids)).first() is not None
        return has_task, "An AI proposal has been generated." if has_task else "Not configured yet (optional)."

    if key == "automation_mode":
        if not websites:
            return False, "Add a website first."
        # Every website always has *some* automation_mode (it defaults
        # to autopilot) -- "configured" means the organization has
        # actually looked at the setting, tracked here via the explicit
        # automation_policy dict ever being written to, or the step
        # being explicitly skipped (acknowledging the default).
        touched = any(bool(w.automation_policy) for w in websites)
        return touched, (
            "Automation mode has been reviewed." if touched else "Using default settings -- review recommended."
        )

    if key == "notifications":
        touched = any(
            "notify_on_regression" in (w.automation_policy or {})
            or "notify_on_auto_pipeline_summary" in (w.automation_policy or {})
            for w in websites
        )
        return touched, "Notification preferences set." if touched else "Using defaults (optional)."

    if key == "explore_dashboard":
        return False, "Visit your dashboard to finish this step."

    raise ValueError(f"Unknown onboarding step: {key}")


def get_onboarding_status(db: Session, organization_id: uuid.UUID) -> dict:
    state = _get_or_create_state(db, organization_id)
    websites = db.query(Website).filter(Website.organization_id == organization_id).all()
    website_ids = [w.id for w in websites]

    steps: list[StepStatus] = []
    for definition in STEP_DEFINITIONS:
        key = definition["key"]
        skipped = key in state.skipped_steps
        completed, detail = _compute_step(key, websites=websites, website_ids=website_ids, db=db, state=state)
        steps.append(
            StepStatus(
                key=key,
                title=definition["title"],
                mandatory=definition["mandatory"],
                completed=completed and not skipped,
                skipped=skipped,
                detail=detail,
            )
        )

    mandatory_incomplete = [s for s in steps if s.mandatory and not s.completed and not s.skipped]
    all_mandatory_complete = len(mandatory_incomplete) == 0

    return {
        "steps": [
            {
                "key": s.key,
                "title": s.title,
                "mandatory": s.mandatory,
                "completed": s.completed,
                "skipped": s.skipped,
                "detail": s.detail,
            }
            for s in steps
        ],
        "welcomed_at": state.welcomed_at,
        "completed_at": state.completed_at,
        "all_mandatory_complete": all_mandatory_complete,
    }


def dismiss_welcome(db: Session, organization_id: uuid.UUID) -> None:
    state = _get_or_create_state(db, organization_id)
    if state.welcomed_at is None:
        state.welcomed_at = datetime.now(timezone.utc)
    db.flush()


def skip_step(db: Session, organization_id: uuid.UUID, step_key: str) -> None:
    if step_key not in OPTIONAL_STEPS:
        raise ValueError(f"'{step_key}' is a mandatory step and cannot be skipped.")
    state = _get_or_create_state(db, organization_id)
    if step_key not in state.skipped_steps:
        state.skipped_steps = [*state.skipped_steps, step_key]
    db.flush()


def unskip_step(db: Session, organization_id: uuid.UUID, step_key: str) -> None:
    state = _get_or_create_state(db, organization_id)
    if step_key in state.skipped_steps:
        state.skipped_steps = [s for s in state.skipped_steps if s != step_key]
    db.flush()


def mark_complete_if_ready(db: Session, organization_id: uuid.UUID) -> bool:
    """Marks onboarding complete only when every mandatory step is
    actually satisfied right now -- never on request alone."""
    status_data = get_onboarding_status(db, organization_id)
    if not status_data["all_mandatory_complete"]:
        return False
    state = _get_or_create_state(db, organization_id)
    if state.completed_at is None:
        state.completed_at = datetime.now(timezone.utc)
        db.flush()
    return True
