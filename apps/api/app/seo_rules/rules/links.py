"""Site-wide internal-link checks: broken links and orphan-page candidates
(RP-0406, MASTER_SPEC.md #8).
"""

from __future__ import annotations

from uuid import UUID

from app.crawler.orchestrator import normalize_frontier_url
from app.models.page import Page
from app.models.page_snapshot import PageSnapshot
from app.models.seo_finding import FindingSeverity
from app.seo_rules.types import FindingCandidate


def check_broken_links(
    pages_by_normalized_url: dict[str, Page],
    snapshots_by_page_id: dict[UUID, PageSnapshot],
) -> list[FindingCandidate]:
    candidates: list[FindingCandidate] = []

    for page_id, snapshot in snapshots_by_page_id.items():
        broken_targets = []
        for link in snapshot.internal_links_json:
            target_page = pages_by_normalized_url.get(normalize_frontier_url(link))
            if target_page is not None and (target_page.last_status_code or 0) >= 400:
                broken_targets.append({"url": link, "status_code": target_page.last_status_code})

        if broken_targets:
            candidates.append(
                FindingCandidate(
                    page_id=page_id,
                    rule_code="BROKEN_INTERNAL_LINK",
                    severity=FindingSeverity.warning,
                    confidence=1.0,
                    evidence={"broken_targets": broken_targets},
                )
            )

    return candidates


def check_orphan_pages(
    sitemap_normalized_urls: set[str],
    pages_by_normalized_url: dict[str, Page],
    snapshots_by_page_id: dict[UUID, PageSnapshot],
) -> list[FindingCandidate]:
    linked_targets: set[str] = set()
    for snapshot in snapshots_by_page_id.values():
        for link in snapshot.internal_links_json:
            linked_targets.add(normalize_frontier_url(link))

    candidates: list[FindingCandidate] = []
    for normalized_url in sitemap_normalized_urls:
        if normalized_url in linked_targets:
            continue
        page = pages_by_normalized_url.get(normalized_url)
        if page is None:
            continue
        candidates.append(
            FindingCandidate(
                page_id=page.id,
                rule_code="ORPHAN_PAGE_CANDIDATE",
                severity=FindingSeverity.info,
                confidence=0.6,
                evidence={"reason": "in sitemap but not linked from any crawled page"},
            )
        )
    return candidates
