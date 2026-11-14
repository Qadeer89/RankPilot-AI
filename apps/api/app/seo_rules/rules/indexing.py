"""Google's own indexing view checks (RankPilot AI Phase 5 "Google
Search Intelligence" -- URL Inspection API).

These compare Google's authoritative indexing state
(PageIndexingStatus, Google's own API response) against what RankPilot
can observe from the crawl itself -- never a RankPilot guess about
whether Google indexed the page.
"""

from __future__ import annotations

from uuid import UUID

from app.crawler.orchestrator import normalize_frontier_url
from app.models.page_indexing_status import PageIndexingStatus
from app.models.seo_finding import FindingSeverity
from app.seo_rules.types import FindingCandidate

# Indexing states the URL Inspection API can report where the page is
# not actually indexable, despite RankPilot's own crawl seeing no
# noindex directive or error status -- Google knows something our
# crawl doesn't (e.g. a robots.txt rule, a duplicate-without-canonical
# decision made server-side).
_BLOCKED_INDEXING_STATES = {
    "BLOCKED_BY_META_TAG",
    "BLOCKED_BY_HTTP_HEADER",
    "BLOCKED_BY_ROBOTS_TXT",
    "BLOCKED_DUE_TO_UNAUTHORIZED_REQUEST",
}


def check(page_id: UUID, indexing_status: PageIndexingStatus | None) -> list[FindingCandidate]:
    if indexing_status is None:
        return []

    candidates: list[FindingCandidate] = []

    if indexing_status.indexing_state in _BLOCKED_INDEXING_STATES:
        candidates.append(
            FindingCandidate(
                page_id=page_id,
                rule_code="GOOGLE_INDEXING_BLOCKED",
                severity=FindingSeverity.critical,
                confidence=1.0,
                evidence={
                    "indexing_state": indexing_status.indexing_state,
                    "verdict": indexing_status.verdict,
                    "coverage_state": indexing_status.coverage_state,
                },
            )
        )

    if (
        indexing_status.google_canonical_url
        and indexing_status.user_canonical_url
        and normalize_frontier_url(indexing_status.google_canonical_url)
        != normalize_frontier_url(indexing_status.user_canonical_url)
    ):
        candidates.append(
            FindingCandidate(
                page_id=page_id,
                rule_code="GOOGLE_CANONICAL_MISMATCH",
                severity=FindingSeverity.warning,
                confidence=0.9,
                evidence={
                    "google_canonical_url": indexing_status.google_canonical_url,
                    "user_canonical_url": indexing_status.user_canonical_url,
                },
            )
        )

    return candidates
