from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.models.seo_finding import FindingSeverity


@dataclass(frozen=True)
class FindingCandidate:
    page_id: uuid.UUID | None
    rule_code: str
    severity: FindingSeverity
    confidence: float
    evidence: dict
