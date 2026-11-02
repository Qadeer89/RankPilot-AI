"""Title, meta description, and heading structure checks (RP-0404).

Length thresholds are heuristics, not confirmed errors
(MASTER_SPEC.md #8: "label heuristics separately from confirmed errors").
"""

from __future__ import annotations

import uuid

from app.models.page_snapshot import PageSnapshot
from app.models.seo_finding import FindingSeverity
from app.seo_rules.types import FindingCandidate

TITLE_MAX_LENGTH = 60
TITLE_MIN_LENGTH = 15
META_DESCRIPTION_MAX_LENGTH = 160


def check(page_id: uuid.UUID, snapshot: PageSnapshot) -> list[FindingCandidate]:
    candidates: list[FindingCandidate] = []

    if not snapshot.title:
        candidates.append(
            FindingCandidate(page_id, "TITLE_MISSING", FindingSeverity.critical, 1.0, {})
        )
    elif len(snapshot.title) > TITLE_MAX_LENGTH:
        candidates.append(
            FindingCandidate(
                page_id,
                "TITLE_TOO_LONG",
                FindingSeverity.info,
                0.6,
                {"length": len(snapshot.title), "threshold": TITLE_MAX_LENGTH},
            )
        )
    elif len(snapshot.title) < TITLE_MIN_LENGTH:
        candidates.append(
            FindingCandidate(
                page_id,
                "TITLE_TOO_SHORT",
                FindingSeverity.info,
                0.5,
                {"length": len(snapshot.title), "threshold": TITLE_MIN_LENGTH},
            )
        )

    if not snapshot.meta_description:
        candidates.append(
            FindingCandidate(page_id, "META_DESCRIPTION_MISSING", FindingSeverity.warning, 1.0, {})
        )
    elif len(snapshot.meta_description) > META_DESCRIPTION_MAX_LENGTH:
        candidates.append(
            FindingCandidate(
                page_id,
                "META_DESCRIPTION_TOO_LONG",
                FindingSeverity.info,
                0.6,
                {"length": len(snapshot.meta_description), "threshold": META_DESCRIPTION_MAX_LENGTH},
            )
        )

    h1_count = len(snapshot.headings_json.get("h1", []))
    if h1_count == 0:
        candidates.append(
            FindingCandidate(page_id, "HEADING_H1_MISSING", FindingSeverity.warning, 1.0, {})
        )
    elif h1_count > 1:
        candidates.append(
            FindingCandidate(
                page_id,
                "HEADING_MULTIPLE_H1",
                FindingSeverity.info,
                0.7,
                {"count": h1_count},
            )
        )

    return candidates
