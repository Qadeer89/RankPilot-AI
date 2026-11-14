"""Severity-weighted SEO health score (0-100), computed once per crawl
and stored against that crawl_job (app/models/site_health_score.py).

Entirely deterministic, grounded in real findings this crawl's rule
engine produced -- no AI involvement, matching the "AI never decides
whether a technical SEO condition passes" rule the rest of the rule
engine already follows (app/seo_rules/engine.py docstring).

A category this codebase has no data source for yet (content quality,
performance) is left as None ("not measured"), never defaulted to a
number, so a dashboard reading this can tell "unavailable" apart from
"measured and perfect."
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.crawl_job import CrawlJob
from app.models.page import Page
from app.models.seo_finding import FindingSeverity, FindingStatus, SEOFinding
from app.models.site_health_score import SiteHealthScore
from app.models.website import Website

# Every rule_code the deterministic engine currently implements
# (app/seo_rules/rules/*.py), split into the two categories this
# codebase can actually evaluate today. Content-quality and performance
# checks (thin content, duplicate body text, Core Web Vitals) don't
# exist yet, so those two category scores stay None rather than being
# computed from an empty/fabricated rule set.
TECHNICAL_RULE_CODES = frozenset(
    {
        "HTTP_ERROR_STATUS",
        "REDIRECT_CHAIN",
        "NOINDEX_DIRECTIVE",
        "CANONICAL_MISSING",
        "CANONICAL_MISMATCH",
        "STRUCTURED_DATA_PARSE_ERROR",
        "BROKEN_INTERNAL_LINK",
        "ORPHAN_PAGE_CANDIDATE",
        "SITEMAP_URL_ERROR",
        "IMAGE_MISSING_SRC",
        "IMAGE_BROKEN",
    }
)
ON_PAGE_RULE_CODES = frozenset(
    {
        "TITLE_MISSING",
        "TITLE_TOO_LONG",
        "TITLE_TOO_SHORT",
        "META_DESCRIPTION_MISSING",
        "META_DESCRIPTION_TOO_LONG",
        "HEADING_H1_MISSING",
        "HEADING_MULTIPLE_H1",
        "DUPLICATE_TITLE",
        "DUPLICATE_META_DESCRIPTION",
        "IMAGE_MISSING_ALT",
        "IMAGE_UNHELPFUL_ALT_TEXT",
        "IMAGE_MISSING_DIMENSIONS",
    }
)
ALL_SCORED_RULE_CODES = TECHNICAL_RULE_CODES | ON_PAGE_RULE_CODES

# A deliberate, documented judgment call, not a fabricated metric: the
# inputs (which rule fired, on how many pages, at what severity) are all
# real; only the point values are a choice. critical issues (e.g. a 5xx
# page) weigh far more than a cosmetic one (e.g. a slightly long title).
SEVERITY_WEIGHT = {
    FindingSeverity.critical: 10.0,
    FindingSeverity.warning: 3.0,
    FindingSeverity.info: 1.0,
}

# Converts "average weighted penalty per page" into a 0-100 point
# deduction. Chosen so a single critical issue present on every page
# (penalty-per-page = 10) costs 50 points -- severe but not an
# automatic zero -- and scales down smoothly from there.
PENALTY_SCALE = 5.0


def _category_score(findings: list[SEOFinding], rule_codes: frozenset[str], page_count: int) -> float | None:
    if page_count == 0:
        return None
    relevant = [f for f in findings if f.rule_code in rule_codes]
    penalty_per_page = sum(SEVERITY_WEIGHT.get(f.severity, 1.0) for f in relevant) / page_count
    return max(0.0, 100.0 - min(penalty_per_page * PENALTY_SCALE, 100.0))


def compute_health_score(db: Session, website: Website, crawl_job: CrawlJob) -> SiteHealthScore:
    page_count = db.query(Page).filter(Page.website_id == website.id).count()
    open_findings = (
        db.query(SEOFinding)
        .filter(SEOFinding.website_id == website.id, SEOFinding.status == FindingStatus.open)
        .all()
    )

    technical_score = _category_score(open_findings, TECHNICAL_RULE_CODES, page_count)
    on_page_score = _category_score(open_findings, ON_PAGE_RULE_CODES, page_count)
    content_score: float | None = None  # not measured yet -- no thin/duplicate-content detection
    performance_score: float | None = None  # not measured yet -- no Core Web Vitals integration

    available = [s for s in (technical_score, on_page_score, content_score, performance_score) if s is not None]
    overall_score = sum(available) / len(available) if available else None

    scored_findings = [f for f in open_findings if f.rule_code in ALL_SCORED_RULE_CODES]
    critical_count = sum(1 for f in scored_findings if f.severity == FindingSeverity.critical)
    warning_count = sum(1 for f in scored_findings if f.severity == FindingSeverity.warning)
    info_count = sum(1 for f in scored_findings if f.severity == FindingSeverity.info)

    # Each page is implicitly "checked" against every scored rule_code;
    # one that didn't fire for a given page counts as passed for it.
    # (A handful of rule_codes are really site/sitemap-level rather than
    # truly per-page -- treating them as per-page here is a deliberate
    # simplification, not an attempt to fabricate a finer-grained result
    # this engine doesn't actually compute.)
    checked = page_count * len(ALL_SCORED_RULE_CODES)
    passed_count = max(checked - len(scored_findings), 0)

    existing = db.query(SiteHealthScore).filter(SiteHealthScore.crawl_job_id == crawl_job.id).one_or_none()
    if existing is None:
        existing = SiteHealthScore(website_id=website.id, crawl_job_id=crawl_job.id)
        db.add(existing)

    existing.overall_score = overall_score
    existing.technical_score = technical_score
    existing.on_page_score = on_page_score
    existing.content_score = content_score
    existing.performance_score = performance_score
    existing.critical_count = critical_count
    existing.warning_count = warning_count
    existing.info_count = info_count
    existing.passed_count = passed_count
    db.flush()
    return existing


def get_score_history(db: Session, website: Website, limit: int = 30) -> list[SiteHealthScore]:
    return (
        db.query(SiteHealthScore)
        .filter(SiteHealthScore.website_id == website.id)
        .order_by(SiteHealthScore.created_at.desc())
        .limit(limit)
        .all()
    )
