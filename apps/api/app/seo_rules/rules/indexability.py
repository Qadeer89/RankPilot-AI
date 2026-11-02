"""Indexability directives and canonical checks (RP-0402)."""

from __future__ import annotations

import uuid

from app.crawler.orchestrator import normalize_frontier_url
from app.models.page_snapshot import PageSnapshot
from app.models.seo_finding import FindingSeverity
from app.seo_rules.types import FindingCandidate


def check(page_id: uuid.UUID, fetched_url: str, snapshot: PageSnapshot) -> list[FindingCandidate]:
    candidates: list[FindingCandidate] = []

    if "noindex" in snapshot.robots_directives:
        candidates.append(
            FindingCandidate(
                page_id=page_id,
                rule_code="NOINDEX_DIRECTIVE",
                severity=FindingSeverity.info,
                confidence=1.0,
                evidence={"directives": snapshot.robots_directives},
            )
        )

    if not snapshot.canonical_url:
        candidates.append(
            FindingCandidate(
                page_id=page_id,
                rule_code="CANONICAL_MISSING",
                severity=FindingSeverity.info,
                confidence=0.8,
                evidence={},
            )
        )
    elif normalize_frontier_url(snapshot.canonical_url) != normalize_frontier_url(fetched_url):
        candidates.append(
            FindingCandidate(
                page_id=page_id,
                rule_code="CANONICAL_MISMATCH",
                severity=FindingSeverity.warning,
                confidence=0.9,
                evidence={"fetched_url": fetched_url, "canonical_url": snapshot.canonical_url},
            )
        )

    return candidates
