"""Heading hierarchy checks (RankPilot AI Phase 3 "Heading Optimization").

H1-presence checks (missing/multiple H1) already exist in metadata.py;
this module adds the one heading signal that needs the full document
order across levels rather than a per-level count: a skipped hierarchy
level (e.g. H1 straight to H3, with no H2 in between), the standard
WCAG/SEO heading-structure heuristic. Detection only -- there is no
operation that rewrites a page's heading markup, since no connector
exposes a generic "set heading text" field separate from page body
content (a known limitation, not an oversight).
"""

from __future__ import annotations

import uuid

from app.models.page_snapshot import PageSnapshot
from app.models.seo_finding import FindingSeverity
from app.seo_rules.types import FindingCandidate


def check_hierarchy(page_id: uuid.UUID, snapshot: PageSnapshot) -> list[FindingCandidate]:
    candidates: list[FindingCandidate] = []

    max_level_seen = 0
    skips: list[dict] = []
    for level in snapshot.heading_sequence_json:
        if level > max_level_seen + 1:
            skips.append({"from_level": max_level_seen, "to_level": level})
        max_level_seen = max(max_level_seen, level)

    if skips:
        candidates.append(
            FindingCandidate(
                page_id=page_id,
                rule_code="HEADING_HIERARCHY_SKIP",
                severity=FindingSeverity.info,
                confidence=0.7,
                evidence={"skips": skips, "sequence": snapshot.heading_sequence_json},
            )
        )

    return candidates
