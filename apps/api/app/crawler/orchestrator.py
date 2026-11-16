"""Crawl coordinator: discovery -> bounded fetch -> extraction -> storage
(RP-0301..RP-0306, SYSTEM_ARCHITECTURE.md #4 "site_crawl" job).

Deliberately synchronous and single-threaded: concurrency is controlled at
the Celery worker level (concurrency 1 on the shared pilot VPS), not inside
a single crawl.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from urllib.parse import urldefrag, urlsplit, urlunsplit

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.deployment import crawler_user_agent
from app.crawler.extract import extract_page
from app.crawler.fetch import FetchError, safe_fetch
from app.crawler.render import RenderError, looks_js_rendered, render_page
from app.crawler.robots import RobotsPolicy, fetch_robots_policy
from app.crawler.sitemap import discover_sitemap_urls
from app.models.crawl_frontier import CrawlFrontier, FrontierState
from app.models.crawl_job import CrawlJob, CrawlStatus, CrawlTrigger
from app.models.page import IndexabilityState, Page
from app.models.page_external_link import ExternalLinkStatus, PageExternalLink
from app.models.page_image import ImageStatus, PageImage
from app.models.page_render_result import PageRenderResult, RenderStatus
from app.models.page_snapshot import PageSnapshot
from app.models.website import Website, WebsiteStatus

logger = logging.getLogger(__name__)

USER_AGENT = crawler_user_agent()

# RP13-008: a polite minimum gap between consecutive requests to the same
# host, since one crawl job fetches many URLs on the same host in a tight
# loop otherwise. robots.txt's own Crawl-delay (if larger) wins.
MIN_CRAWL_DELAY_SECONDS = 0.5

# Bounds one crawl's worth of *outbound* verification requests to
# other sites' domains, not this site's -- without a cap, a page with
# hundreds of external links would turn one crawl into hundreds of
# extra network round-trips to third-party hosts outside this site's
# own crawl_budget accounting. Links past the cap stay "unchecked"
# (not a false "ok") and get picked up on a later crawl.
MAX_EXTERNAL_LINKS_VERIFIED_PER_CRAWL = 20
EXTERNAL_LINK_CHECK_TIMEOUT_SECONDS = 5.0


def _throttle(robots_policy: RobotsPolicy, user_agent: str) -> None:
    delay = max(MIN_CRAWL_DELAY_SECONDS, robots_policy.crawl_delay(user_agent) or 0.0)
    if delay > 0:
        time.sleep(delay)


def normalize_frontier_url(url: str) -> str:
    url, _fragment = urldefrag(url)
    parts = urlsplit(url)
    path = parts.path or "/"
    # A trailing slash on anything but the root is not a distinct URL in
    # practice (both resolve to the same page), but without stripping it
    # here two equally-valid spellings of the same page (one from the
    # crawler, one from an external source like Google Search Console's
    # "page" dimension -- app/integrations/search_console_sync.py) fail
    # to match and are silently treated as different pages.
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, parts.query, ""))


def _resolve_indexability(status_code: int, meta_robots: list[str]) -> IndexabilityState:
    # Pages blocked by robots.txt never reach here: they're skipped before
    # fetch, so this only distinguishes noindex / unknown / indexable.
    if "noindex" in meta_robots:
        return IndexabilityState.noindex
    if status_code >= 400:
        return IndexabilityState.unknown
    return IndexabilityState.indexable


def _add_frontier_entry(
    db: Session,
    website: Website,
    known_urls: set[str],
    url: str,
    *,
    priority: int,
    discovered_from: str | None,
) -> None:
    normalized = normalize_frontier_url(url)
    if normalized in known_urls:
        return
    known_urls.add(normalized)
    db.add(
        CrawlFrontier(
            website_id=website.id,
            url=normalized,
            priority=priority,
            discovered_from=discovered_from,
            state=FrontierState.pending,
        )
    )


def _seed_frontier(db: Session, website: Website, robots_policy, known_urls: set[str]) -> None:
    sitemap_urls = discover_sitemap_urls(
        website.canonical_url, robots_policy.sitemap_urls, user_agent=USER_AGENT
    )

    _add_frontier_entry(db, website, known_urls, website.canonical_url, priority=100, discovered_from=None)
    for url in sitemap_urls:
        _add_frontier_entry(db, website, known_urls, url, priority=50, discovered_from="sitemap")
    db.flush()


def _sync_page_images(db: Session, page: Page, images: list) -> None:
    """Replace a page's PageImage rows with this crawl's fresh extraction.

    PageImage reflects current HTML, not history (like Page itself), so a
    page that's refetched gets its old rows discarded rather than
    accumulating duplicates for images that no longer exist.
    """
    db.query(PageImage).filter(PageImage.page_id == page.id).delete()
    for image in images:
        db.add(
            PageImage(
                page_id=page.id,
                image_src=image.src,
                alt_text=image.alt_text,
                has_alt=image.has_alt,
                is_decorative=image.is_decorative,
                has_dimensions=image.has_dimensions,
                image_status=ImageStatus.ok if image.src else ImageStatus.missing_src,
            )
        )


def _sync_page_external_links(db: Session, page: Page, external_links: list) -> None:
    """Replace a page's PageExternalLink rows with this crawl's fresh
    extraction -- same current-state contract as _sync_page_images.
    """
    db.query(PageExternalLink).filter(PageExternalLink.page_id == page.id).delete()
    for link in external_links:
        db.add(
            PageExternalLink(
                page_id=page.id,
                url=link.url,
                is_nofollow=link.is_nofollow,
                is_sponsored=link.is_sponsored,
                is_ugc=link.is_ugc,
            )
        )


def _verify_external_links(db: Session, website: Website, page_ids: set) -> None:
    """Live-check a bounded number of this crawl's distinct external
    link URLs and record ok/redirect/broken -- the one place this
    crawler deliberately fetches a URL it doesn't control or verify
    ahead of time belongs to this site (SECURITY_SPECIFICATION.md #4's
    SSRF protections still apply: safe_fetch re-validates every hop).
    """
    if not page_ids:
        return
    rows = (
        db.query(PageExternalLink)
        .filter(PageExternalLink.page_id.in_(page_ids), PageExternalLink.link_status == ExternalLinkStatus.unchecked)
        .all()
    )
    rows_by_url: dict[str, list[PageExternalLink]] = {}
    for row in rows:
        rows_by_url.setdefault(row.url, []).append(row)

    checked = 0
    for url, url_rows in rows_by_url.items():
        if checked >= MAX_EXTERNAL_LINKS_VERIFIED_PER_CRAWL:
            break
        checked += 1
        try:
            result = safe_fetch(url, user_agent=USER_AGENT, timeout=EXTERNAL_LINK_CHECK_TIMEOUT_SECONDS)
        except FetchError:
            status = ExternalLinkStatus.broken
        else:
            if result.status_code >= 400:
                status = ExternalLinkStatus.broken
            elif result.redirect_chain:
                status = ExternalLinkStatus.redirect
            else:
                status = ExternalLinkStatus.ok
        for row in url_rows:
            row.link_status = status


def _maybe_render_page(db: Session, page: Page, *, final_url: str, raw_html: str, raw_word_count: int) -> None:
    """Attempt headless rendering only when the raw HTML looks
    JS-dependent (app/crawler/render.py's narrow heuristic) -- most
    pages never reach this far. Replaces any prior PageRenderResult
    for this page, the same current-state contract PageImage follows.
    """
    db.query(PageRenderResult).filter(PageRenderResult.page_id == page.id).delete()

    if not looks_js_rendered(raw_html=raw_html, word_count=raw_word_count):
        return

    try:
        rendered = render_page(final_url)
    except RenderError as exc:
        db.add(
            PageRenderResult(
                page_id=page.id,
                render_status=RenderStatus.failed,
                raw_word_count=raw_word_count,
                rendered_word_count=None,
                error_message=str(exc)[:1024],
            )
        )
        return

    rendered_extraction = extract_page(rendered.html, base_url=final_url, site_hostname=urlsplit(final_url).hostname or "")
    db.add(
        PageRenderResult(
            page_id=page.id,
            render_status=RenderStatus.ok,
            raw_word_count=raw_word_count,
            rendered_word_count=rendered_extraction.word_count,
        )
    )


def _upsert_page(db: Session, website: Website, normalized_url: str, canonical_url: str) -> Page:
    page = (
        db.query(Page)
        .filter(Page.website_id == website.id, Page.normalized_url == normalized_url)
        .one_or_none()
    )
    now = datetime.now(timezone.utc)
    if page is None:
        page = Page(
            website_id=website.id,
            canonical_url=canonical_url,
            normalized_url=normalized_url,
            first_seen_at=now,
            last_seen_at=now,
        )
        db.add(page)
        db.flush()
    else:
        page.last_seen_at = now
    return page


# Non-crawlable system paths a link-extraction rule now excludes, but which
# an earlier crawl (before that rule existed) may already have persisted as
# a CrawlFrontier row. Without this cleanup, such a row survives the
# per-website frontier reset forever and keeps getting re-fetched, and its
# backing Page's findings/opportunities never resolve since the page is
# never in a crawl's snapshot scope again (app/seo_rules/engine.py).
NON_CRAWLABLE_URL_SUBSTRINGS = ("/cdn-cgi/",)


def _purge_non_crawlable_frontier_entries(db: Session, website: Website) -> None:
    stale_filters = [CrawlFrontier.url.like(f"%{substring}%") for substring in NON_CRAWLABLE_URL_SUBSTRINGS]
    stale_urls = {
        row[0]
        for row in db.query(CrawlFrontier.url)
        .filter(CrawlFrontier.website_id == website.id, or_(*stale_filters))
        .all()
    }
    if not stale_urls:
        return
    db.query(Page).filter(Page.website_id == website.id, Page.normalized_url.in_(stale_urls)).delete(
        synchronize_session=False
    )
    db.query(CrawlFrontier).filter(
        CrawlFrontier.website_id == website.id, CrawlFrontier.url.in_(stale_urls)
    ).delete(synchronize_session=False)
    db.flush()


def create_crawl_job(db: Session, website: Website, *, trigger: CrawlTrigger = CrawlTrigger.manual) -> CrawlJob:
    """Create a pending CrawlJob row. Split from `run_crawl` so an API
    endpoint can hand the caller a job id immediately and let a worker
    actually run the crawl against that same row.
    """
    crawl_job = CrawlJob(website_id=website.id, trigger=trigger, status=CrawlStatus.pending)
    db.add(crawl_job)
    db.flush()
    return crawl_job


def _prepare_targeted_frontier(db: Session, website: Website, urls: list[str]) -> set[str]:
    """For a one-URL verification crawl: make sure each URL has a pending
    frontier entry, touching no other entry of the website."""
    targeted: set[str] = set()
    for url in urls:
        normalized = normalize_frontier_url(url)
        targeted.add(normalized)
        entry = (
            db.query(CrawlFrontier)
            .filter(CrawlFrontier.website_id == website.id, CrawlFrontier.url == normalized)
            .one_or_none()
        )
        if entry is None:
            db.add(
                CrawlFrontier(
                    website_id=website.id,
                    url=normalized,
                    priority=100,
                    discovered_from="post_change",
                    state=FrontierState.pending,
                )
            )
        else:
            entry.state = FrontierState.pending
            entry.next_fetch_at = None
    db.flush()
    return targeted


def run_crawl(
    db: Session,
    website: Website,
    crawl_job: CrawlJob | None = None,
    *,
    trigger: CrawlTrigger = CrawlTrigger.manual,
    only_urls: list[str] | None = None,
) -> CrawlJob:
    """Run one bounded crawl of `website` and persist pages/snapshots.

    If `crawl_job` is omitted, one is created here (convenient for direct,
    synchronous calls such as tests). Caller owns the transaction overall
    (commits/rolls back around this call once it returns), but this
    function commits `crawl_job.status`/`pages_fetched`/`pages_requested`
    as it goes -- without that, another request (the dashboard polling
    for progress) would see this crawl as still "pending" with 0/0 pages
    the entire time it runs, instead of "running" with live counts, since
    nothing else would make those intermediate writes visible outside this
    session until the whole crawl finished.
    """
    if crawl_job is None:
        crawl_job = create_crawl_job(db, website, trigger=trigger)

    crawl_job.status = CrawlStatus.running
    crawl_job.started_at = datetime.now(timezone.utc)
    db.commit()

    targeted_urls: set[str] | None = None
    try:
        if only_urls is None:
            _purge_non_crawlable_frontier_entries(db, website)

            # The frontier is a long-lived, per-website structure (one row per
            # URL ever seen), not per-crawl: without this, a URL already fetched
            # by an earlier crawl would never be considered "pending" again, and
            # a second crawl of the same site would fetch nothing at all.
            db.query(CrawlFrontier).filter(CrawlFrontier.website_id == website.id).update(
                {"state": FrontierState.pending}
            )

        robots_policy = fetch_robots_policy(website.canonical_url, user_agent=USER_AGENT)
        known_urls: set[str] = {
            row[0]
            for row in db.query(CrawlFrontier.url).filter(CrawlFrontier.website_id == website.id).all()
        }
        if only_urls is None:
            _seed_frontier(db, website, robots_policy, known_urls)
        else:
            # Verification crawl of specific URLs only: no sitemap seeding,
            # no link discovery, no other frontier entry is touched.
            targeted_urls = _prepare_targeted_frontier(db, website, only_urls)

        pages_fetched = 0
        pages_requested = 0
        errors: list[str] = []
        cancelled_reason: str | None = None
        fetched_page_ids: set = set()

        while pages_requested < website.crawl_budget:
            # RP13-010: pick up an external cancel (POST .../cancel) or a
            # website pause issued by another request while this crawl is
            # mid-run. Both are committed by a different session, so these
            # ORM objects must be refreshed rather than trusted from
            # memory.
            db.refresh(crawl_job)
            if crawl_job.status == CrawlStatus.cancelled:
                cancelled_reason = "Crawl was cancelled."
                break
            db.refresh(website)
            if website.status != WebsiteStatus.active:
                cancelled_reason = "Website automation was paused during the crawl."
                break

            # Coverage rotation: when a site has more URLs than crawl_budget,
            # ordering purely by priority would re-select the same top-N
            # URLs forever and never reach the rest. URLs never fetched
            # (next_fetch_at IS NULL) always go first so a brand-new site
            # gets full first-pass coverage; once everything has been seen
            # at least once, the least-recently-fetched URL goes first
            # (next_fetch_at ASC) so coverage rotates across crawls instead
            # of a fixed priority tier starving everything below it.
            pending_query = db.query(CrawlFrontier).filter(
                CrawlFrontier.website_id == website.id,
                CrawlFrontier.state == FrontierState.pending,
            )
            if targeted_urls is not None:
                pending_query = pending_query.filter(CrawlFrontier.url.in_(targeted_urls))
            frontier_entry = (
                pending_query
                .order_by(
                    CrawlFrontier.next_fetch_at.is_(None).desc(),
                    CrawlFrontier.next_fetch_at.asc(),
                    CrawlFrontier.priority.desc(),
                    CrawlFrontier.created_at.asc(),
                )
                .first()
            )
            if frontier_entry is None:
                break

            pages_requested += 1

            if not robots_policy.can_fetch(frontier_entry.url, USER_AGENT):
                frontier_entry.state = FrontierState.skipped
                frontier_entry.next_fetch_at = datetime.now(timezone.utc)
                crawl_job.pages_requested = pages_requested
                crawl_job.pages_fetched = pages_fetched
                db.commit()
                continue

            try:
                result = safe_fetch(frontier_entry.url, user_agent=USER_AGENT)
            except FetchError as exc:
                frontier_entry.state = FrontierState.error
                frontier_entry.next_fetch_at = datetime.now(timezone.utc)
                errors.append(f"{frontier_entry.url}: {exc}")
                crawl_job.pages_requested = pages_requested
                crawl_job.pages_fetched = pages_fetched
                db.commit()
                _throttle(robots_policy, USER_AGENT)
                continue

            frontier_entry.state = FrontierState.fetched
            frontier_entry.next_fetch_at = datetime.now(timezone.utc)
            normalized = normalize_frontier_url(result.final_url)
            page = _upsert_page(db, website, normalized, result.final_url)

            extraction = extract_page(result.body, base_url=result.final_url, site_hostname=website.hostname)
            indexability = _resolve_indexability(result.status_code, extraction.meta_robots_directives)
            page.last_status_code = result.status_code
            page.indexability_state = indexability
            page.content_hash = extraction.content_fingerprint

            db.add(
                PageSnapshot(
                    page_id=page.id,
                    crawl_job_id=crawl_job.id,
                    fetched_at=datetime.now(timezone.utc),
                    status_code=result.status_code,
                    redirect_count=len(result.redirect_chain),
                    title=extraction.title,
                    meta_description=extraction.meta_description,
                    canonical_url=extraction.canonical_url,
                    robots_directives=extraction.meta_robots_directives,
                    headings_json=extraction.headings,
                    heading_sequence_json=extraction.heading_sequence,
                    schema_json=[
                        {"raw": b.raw, "parsed": b.parsed, "parse_error": b.parse_error}
                        for b in extraction.structured_data
                    ],
                    internal_links_json=extraction.internal_links,
                    content_fingerprint=extraction.content_fingerprint,
                    word_count=extraction.word_count,
                    rel_next_url=extraction.rel_next_url,
                    rel_prev_url=extraction.rel_prev_url,
                    viewport_content=extraction.viewport_content,
                )
            )
            _sync_page_images(db, page, extraction.images)
            _sync_page_external_links(db, page, extraction.external_links)
            _maybe_render_page(
                db,
                page,
                final_url=result.final_url,
                raw_html=result.body,
                raw_word_count=extraction.word_count,
            )
            fetched_page_ids.add(page.id)
            pages_fetched += 1

            remaining_budget = website.crawl_budget - pages_requested
            if remaining_budget > 0 and targeted_urls is None:
                for link in extraction.internal_links[:remaining_budget]:
                    _add_frontier_entry(
                        db,
                        website,
                        known_urls,
                        link,
                        priority=10,
                        discovered_from=frontier_entry.url,
                    )
            crawl_job.pages_requested = pages_requested
            crawl_job.pages_fetched = pages_fetched
            db.commit()
            _throttle(robots_policy, USER_AGENT)

        _verify_external_links(db, website, fetched_page_ids)

        crawl_job.status = CrawlStatus.cancelled if cancelled_reason else CrawlStatus.completed
        crawl_job.pages_requested = pages_requested
        crawl_job.pages_fetched = pages_fetched
        summary_parts = ([cancelled_reason] if cancelled_reason else []) + errors[:20]
        crawl_job.error_summary = "; ".join(summary_parts) if summary_parts else None
        crawl_job.completed_at = datetime.now(timezone.utc)
        db.flush()
        return crawl_job
    except Exception as exc:
        logger.exception("Crawl failed for website %s", website.id)
        crawl_job.status = CrawlStatus.failed
        crawl_job.error_summary = str(exc)[:2000]
        crawl_job.completed_at = datetime.now(timezone.utc)
        db.flush()
        return crawl_job
