"""Structured data (JSON-LD) syntax validation (RP-0405)."""

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

    return candidates
