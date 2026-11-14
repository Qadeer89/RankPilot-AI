"""Pagination checks (RankPilot AI Phase 2 "Pagination Detection").

Report-only: these findings describe a declared rel=next/prev
relationship and whether it's internally consistent, but nothing here
-- or anywhere downstream of a PAGINATION_* finding -- changes a URL,
a canonical tag, or the pagination markup itself. There is no
operation for it, matching the feature's explicit "report-only, no
automatic URL changes" requirement.
"""

from __future__ import annotations

from uuid import UUID

from app.crawler.orchestrator import normalize_frontier_url
from app.models.page import Page
from app.models.page_snapshot import PageSnapshot
from app.models.seo_finding import FindingSeverity
from app.seo_rules.types import FindingCandidate


def check(page_id: UUID, fetched_url: str, snapshot: PageSnapshot) -> list[FindingCandidate]:
    """Per-page checks needing only this page's own snapshot."""
    candidates: list[FindingCandidate] = []

    # A page declaring rel=prev is, by definition, not the first page in
    # its series -- Google's long-standing guidance (still followed by
    # most pagination templates even after rel=next/prev stopped
    # affecting ranking) is that such a page's canonical should point to
    # itself, not to page 1 or any other URL, so each page's own content
    # stays indexable rather than being folded into a different page.
    if (
        snapshot.rel_prev_url
        and snapshot.canonical_url
        and normalize_frontier_url(snapshot.canonical_url) != normalize_frontier_url(fetched_url)
    ):
        candidates.append(
            FindingCandidate(
                page_id=page_id,
                rule_code="PAGINATION_CANONICAL_CONFLICT",
                severity=FindingSeverity.warning,
                confidence=0.8,
                evidence={
                    "fetched_url": fetched_url,
                    "canonical_url": snapshot.canonical_url,
                    "rel_prev_url": snapshot.rel_prev_url,
                },
            )
        )

    return candidates


def check_broken_pagination_links(
    pages_by_normalized_url: dict[str, Page],
    snapshots_by_page_id: dict[UUID, PageSnapshot],
) -> list[FindingCandidate]:
    """Site-wide: flag a rel=next/prev target this site already crawled
    and knows returned an error status -- the same never-fetch-something-
    new approach links.check_broken_links already uses for <a href>.
    """
    candidates: list[FindingCandidate] = []

    for page_id, snapshot in snapshots_by_page_id.items():
        broken_targets = []
        for rel, url in (("next", snapshot.rel_next_url), ("prev", snapshot.rel_prev_url)):
            if not url:
                continue
            target_page = pages_by_normalized_url.get(normalize_frontier_url(url))
            if target_page is not None and (target_page.last_status_code or 0) >= 400:
                broken_targets.append({"rel": rel, "url": url, "status_code": target_page.last_status_code})

        if broken_targets:
            candidates.append(
                FindingCandidate(
                    page_id=page_id,
                    rule_code="PAGINATION_LINK_BROKEN",
                    severity=FindingSeverity.warning,
                    confidence=1.0,
                    evidence={"broken_targets": broken_targets},
                )
            )

    return candidates
