"""Structured data (JSON-LD) syntax validation and presence check
(RP-0405, RankPilot AI Phase 3 "Schema Markup Automation").
"""

from __future__ import annotations

import uuid

from app.models.page_snapshot import PageSnapshot
from app.models.seo_finding import FindingSeverity
from app.seo_rules.types import FindingCandidate

_RAW_SNIPPET_LENGTH = 200


def check(page_id: uuid.UUID, snapshot: PageSnapshot) -> list[FindingCandidate]:
    candidates: list[FindingCandidate] = []

    for index, block in enumerate(snapshot.schema_json):
        if block.get("parse_error"):
            candidates.append(
                FindingCandidate(
                    page_id=page_id,
                    rule_code="STRUCTURED_DATA_PARSE_ERROR",
                    severity=FindingSeverity.warning,
                    confidence=1.0,
                    evidence={
                        "block_index": index,
                        "error": block["parse_error"],
                        "raw_snippet": (block.get("raw") or "")[:_RAW_SNIPPET_LENGTH],
                    },
                )
            )

    # A heuristic, not a confirmed error (MASTER_SPEC.md #8): not every
    # page benefits equally from structured data, so this fires at low
    # confidence and info severity rather than being treated as a
    # defect the way a parse error is.
    if not snapshot.schema_json:
        candidates.append(
            FindingCandidate(
                page_id=page_id,
                rule_code="STRUCTURED_DATA_MISSING",
                severity=FindingSeverity.info,
                confidence=0.5,
                evidence={},
            )
        )

    return candidates
