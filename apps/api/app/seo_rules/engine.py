"""Deterministic SEO rule engine: evaluates one crawl's snapshots and
upserts evidence-backed findings (RP-0407, SEO_AUTOMATION_ENGINE.md #1).

AI never decides whether a technical SEO condition passes — only this
engine does (MASTER_SPEC.md "Global implementation rules").
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.orm import Session

from app.crawler.orchestrator import normalize_frontier_url
from app.models.crawl_frontier import CrawlFrontier
from app.models.crawl_job import CrawlJob
from app.models.page import Page
from app.models.page_external_link import PageExternalLink
from app.models.page_image import PageImage
from app.models.page_render_result import PageRenderResult
from app.models.page_snapshot import PageSnapshot
from app.models.performance_metric import PerformanceMetric, PerformanceStrategy
from app.models.seo_finding import FindingStatus, SEOFinding
from app.models.website import Website
from app.seo_rules.rules import (
    content,
    duplicates,
    external_links,
    headings,
    http_status,
    images,
    indexability,
    links,
    metadata,
    mobile,
    pagination,
    performance,
    rendering,
    sitemap,
    structured_data,
)
from app.seo_rules.types import FindingCandidate


def _latest_snapshots_for_crawl(db: Session, crawl_job_id: UUID) -> dict[UUID, PageSnapshot]:
    snapshots = db.query(PageSnapshot).filter(PageSnapshot.crawl_job_id == crawl_job_id).all()
    return {s.page_id: s for s in snapshots}


def _all_pages_by_normalized_url(db: Session, website_id: UUID) -> dict[str, Page]:
    pages = db.query(Page).filter(Page.website_id == website_id).all()
    return {p.normalized_url: p for p in pages}


def _page_images_by_page_id(db: Session, page_ids: set[UUID]) -> dict[UUID, list[PageImage]]:
    if not page_ids:
        return {}
    rows = db.query(PageImage).filter(PageImage.page_id.in_(page_ids)).all()
    grouped: dict[UUID, list[PageImage]] = {}
    for row in rows:
        grouped.setdefault(row.page_id, []).append(row)
    return grouped


def _page_external_links_by_page_id(db: Session, page_ids: set[UUID]) -> dict[UUID, list[PageExternalLink]]:
    if not page_ids:
        return {}
    rows = db.query(PageExternalLink).filter(PageExternalLink.page_id.in_(page_ids)).all()
    grouped: dict[UUID, list[PageExternalLink]] = {}
    for row in rows:
        grouped.setdefault(row.page_id, []).append(row)
    return grouped


def _page_render_results_by_page_id(db: Session, page_ids: set[UUID]) -> dict[UUID, PageRenderResult]:
    if not page_ids:
        return {}
    rows = db.query(PageRenderResult).filter(PageRenderResult.page_id.in_(page_ids)).all()
    return {row.page_id: row for row in rows}


def _page_performance_metrics_by_page_id(db: Session, page_ids: set[UUID]) -> dict[UUID, PerformanceMetric]:
    if not page_ids:
        return {}
    rows = (
        db.query(PerformanceMetric)
        .filter(PerformanceMetric.page_id.in_(page_ids), PerformanceMetric.strategy == PerformanceStrategy.mobile)
        .all()
    )
    return {row.page_id: row for row in rows}


def _sitemap_normalized_urls(db: Session, website_id: UUID) -> set[str]:
    rows = (
        db.query(CrawlFrontier.url)
        .filter(CrawlFrontier.website_id == website_id, CrawlFrontier.discovered_from == "sitemap")
        .all()
    )
    return {row[0] for row in rows}


# Rule codes produced only by iterating this crawl's fresh snapshots. A
# finding with one of these codes is only eligible to auto-resolve for a
# page that actually got a fresh snapshot this crawl — never for a page the
# crawl budget skipped, even if that page is otherwise "known" (e.g. via the
# sitemap).
SNAPSHOT_SCOPED_RULE_CODES = {
    "HTTP_ERROR_STATUS",
    "REDIRECT_CHAIN",
    "NOINDEX_DIRECTIVE",
    "CANONICAL_MISSING",
    "CANONICAL_MISMATCH",
    "TITLE_MISSING",
    "TITLE_TOO_LONG",
    "TITLE_TOO_SHORT",
    "META_DESCRIPTION_MISSING",
    "META_DESCRIPTION_TOO_LONG",
    "HEADING_H1_MISSING",
    "HEADING_MULTIPLE_H1",
    "STRUCTURED_DATA_PARSE_ERROR",
    "STRUCTURED_DATA_MISSING",
    "DUPLICATE_TITLE",
    "DUPLICATE_META_DESCRIPTION",
    "BROKEN_INTERNAL_LINK",
    "IMAGE_MISSING_SRC",
    "IMAGE_MISSING_ALT",
    "IMAGE_UNHELPFUL_ALT_TEXT",
    "IMAGE_MISSING_DIMENSIONS",
    "IMAGE_BROKEN",
    "THIN_CONTENT",
    "DUPLICATE_BODY_CONTENT",
    "EXTERNAL_LINK_BROKEN",
    "EXTERNAL_LINK_REDIRECT",
    "PAGINATION_CANONICAL_CONFLICT",
    "PAGINATION_LINK_BROKEN",
    "HEADING_HIERARCHY_SKIP",
    "JS_RENDERING_CONTENT_GAP",
    "RENDER_FAILURE",
    "MOBILE_VIEWPORT_MISSING",
    "MOBILE_VIEWPORT_NOT_RESPONSIVE",
    "PERFORMANCE_OPTIMIZATION_OPPORTUNITY",
}

# Rule codes derived from persistent Page/sitemap state rather than this
# crawl's snapshots — these can legitimately resolve even for a page this
# particular crawl didn't re-fetch, since they're recomputed from the same
# persistent state every run.
SITEMAP_SCOPED_RULE_CODES = {"SITEMAP_URL_ERROR", "ORPHAN_PAGE_CANDIDATE"}


def _persist_findings(
    db: Session,
    website: Website,
    candidates: list[FindingCandidate],
    *,
    snapshot_scope: set[UUID],
    sitemap_scope: set[UUID],
) -> list[SEOFinding]:
    now = datetime.now(timezone.utc)
    touched_keys: set[tuple[UUID | None, str]] = set()
    persisted: list[SEOFinding] = []

    for candidate in candidates:
        key = (candidate.page_id, candidate.rule_code)
        touched_keys.add(key)

        existing = (
            db.query(SEOFinding)
            .filter(
                SEOFinding.website_id == website.id,
                SEOFinding.page_id == candidate.page_id,
                SEOFinding.rule_code == candidate.rule_code,
            )
            .one_or_none()
        )
        if existing is None:
            finding = SEOFinding(
                website_id=website.id,
                page_id=candidate.page_id,
                rule_code=candidate.rule_code,
                severity=candidate.severity,
                confidence=candidate.confidence,
                evidence_json=candidate.evidence,
                first_detected_at=now,
                last_detected_at=now,
                status=FindingStatus.open,
            )
            db.add(finding)
        else:
            existing.severity = candidate.severity
            existing.confidence = candidate.confidence
            existing.evidence_json = candidate.evidence
            existing.last_detected_at = now
            existing.status = FindingStatus.open
            finding = existing
        persisted.append(finding)

    db.flush()

    relevant_page_ids = snapshot_scope | sitemap_scope
    if relevant_page_ids:
        previously_open = (
            db.query(SEOFinding)
            .filter(
                SEOFinding.website_id == website.id,
                SEOFinding.status == FindingStatus.open,
                SEOFinding.page_id.in_(relevant_page_ids),
            )
            .all()
        )
        for finding in previously_open:
            if finding.rule_code in SNAPSHOT_SCOPED_RULE_CODES:
                in_scope = finding.page_id in snapshot_scope
            elif finding.rule_code in SITEMAP_SCOPED_RULE_CODES:
                in_scope = finding.page_id in sitemap_scope
            else:
                in_scope = False
            if in_scope and (finding.page_id, finding.rule_code) not in touched_keys:
                finding.status = FindingStatus.resolved

    # Flush so a caller that immediately runs another read (e.g.
    # refresh_opportunities_for_website, in the same transaction) sees these
    # status changes rather than stale pre-mutation rows: the production
    # session runs with autoflush=False.
    db.flush()
    return persisted


def run_rules_for_crawl(db: Session, website: Website, crawl_job: CrawlJob) -> list[SEOFinding]:
    snapshots_by_page_id = _latest_snapshots_for_crawl(db, crawl_job.id)
    pages_by_normalized_url = _all_pages_by_normalized_url(db, website.id)
    pages_by_id = {p.id: p for p in pages_by_normalized_url.values()}
    sitemap_urls = _sitemap_normalized_urls(db, website.id)
    page_images_by_page_id = _page_images_by_page_id(db, set(snapshots_by_page_id.keys()))
    page_external_links_by_page_id = _page_external_links_by_page_id(db, set(snapshots_by_page_id.keys()))
    page_render_results_by_page_id = _page_render_results_by_page_id(db, set(snapshots_by_page_id.keys()))
    page_performance_metrics_by_page_id = _page_performance_metrics_by_page_id(db, set(snapshots_by_page_id.keys()))

    candidates: list[FindingCandidate] = []

    for page_id, snapshot in snapshots_by_page_id.items():
        page = pages_by_id[page_id]
        candidates.extend(http_status.check(page_id, snapshot))
        candidates.extend(indexability.check(page_id, page.canonical_url, snapshot))
        candidates.extend(metadata.check(page_id, snapshot))
        candidates.extend(structured_data.check(page_id, snapshot))
        candidates.extend(images.check(page_id, page_images_by_page_id.get(page_id, [])))
        candidates.extend(content.check_thin_content(page_id, snapshot))
        candidates.extend(external_links.check(page_id, page_external_links_by_page_id.get(page_id, [])))
        candidates.extend(pagination.check(page_id, page.canonical_url, snapshot))
        candidates.extend(headings.check_hierarchy(page_id, snapshot))
        candidates.extend(rendering.check(page_id, page_render_results_by_page_id.get(page_id)))
        candidates.extend(mobile.check(page_id, snapshot))
        candidates.extend(performance.check(page_id, page_performance_metrics_by_page_id.get(page_id)))

    candidates.extend(duplicates.check_site(snapshots_by_page_id))
    candidates.extend(content.check_duplicate_body_content(snapshots_by_page_id))
    candidates.extend(links.check_broken_links(pages_by_normalized_url, snapshots_by_page_id))
    candidates.extend(links.check_orphan_pages(sitemap_urls, pages_by_normalized_url, snapshots_by_page_id))
    candidates.extend(sitemap.check_sitemap_urls(sitemap_urls, pages_by_normalized_url))
    candidates.extend(
        images.check_broken_images(
            pages_by_normalized_url, page_images_by_page_id, normalize_frontier_url
        )
    )
    candidates.extend(pagination.check_broken_pagination_links(pages_by_normalized_url, snapshots_by_page_id))

    snapshot_scope = set(snapshots_by_page_id.keys())
    sitemap_scope = {
        pages_by_normalized_url[u].id for u in sitemap_urls if u in pages_by_normalized_url
    }

    return _persist_findings(
        db, website, candidates, snapshot_scope=snapshot_scope, sitemap_scope=sitemap_scope
    )
