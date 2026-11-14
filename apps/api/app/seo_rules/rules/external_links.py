"""External-link checks (RankPilot AI Phase 2 "External Link Audit").

Operates only on PageExternalLink rows already verified this crawl
(app/crawler/orchestrator.py:_verify_external_links) -- an "unchecked"
link (past the per-crawl verification cap, or not yet checked) never
produces a finding, since that would fabricate a verdict RankPilot
hasn't actually confirmed.
"""

from __future__ import annotations

from uuid import UUID

from app.models.page_external_link import ExternalLinkStatus, PageExternalLink
from app.models.seo_finding import FindingSeverity
from app.seo_rules.types import FindingCandidate


def check(page_id: UUID, external_links: list[PageExternalLink]) -> list[FindingCandidate]:
    candidates: list[FindingCandidate] = []
    if not external_links:
        return candidates

    broken = [link for link in external_links if link.link_status == ExternalLinkStatus.broken]
    if broken:
        candidates.append(
            FindingCandidate(
                page_id=page_id,
                rule_code="EXTERNAL_LINK_BROKEN",
                severity=FindingSeverity.warning,
                confidence=1.0,
                evidence={"count": len(broken), "urls": [link.url for link in broken][:20]},
            )
        )

    redirecting = [link for link in external_links if link.link_status == ExternalLinkStatus.redirect]
    if redirecting:
        candidates.append(
            FindingCandidate(
                page_id=page_id,
                rule_code="EXTERNAL_LINK_REDIRECT",
                severity=FindingSeverity.info,
                confidence=1.0,
                evidence={"count": len(redirecting), "urls": [link.url for link in redirecting][:20]},
            )
        )

    return candidates
