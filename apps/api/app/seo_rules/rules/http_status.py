"""HTTP status, redirect chain, and broken-link checks (RP-0401)."""

from __future__ import annotations

import uuid

from app.models.page_snapshot import PageSnapshot
from app.models.seo_finding import FindingSeverity
from app.seo_rules.types import FindingCandidate

MAX_HEALTHY_REDIRECTS = 1


def check(page_id: uuid.UUID, snapshot: PageSnapshot) -> list[FindingCandidate]:
    candidates: list[FindingCandidate] = []

    if snapshot.status_code is None or snapshot.status_code >= 400:
        severity = FindingSeverity.critical if (snapshot.status_code or 0) >= 500 else FindingSeverity.warning
        candidates.append(
            FindingCandidate(
                page_id=page_id,
                rule_code="HTTP_ERROR_STATUS",
                severity=severity,
                confidence=1.0,
                evidence={"status_code": snapshot.status_code},
            )
        )

    if snapshot.redirect_count > MAX_HEALTHY_REDIRECTS:
        candidates.append(
            FindingCandidate(
                page_id=page_id,
                rule_code="REDIRECT_CHAIN",
                severity=FindingSeverity.warning,
                confidence=1.0,
                evidence={"hops": snapshot.redirect_count},
            )
        )

    return candidates
