"""Mobile SEO checks (RankPilot AI Phase 4 "Mobile SEO").

Deterministic, declared-markup checks only -- no visual rendering or
device-emulation is done here (app/crawler/render.py is a separate,
selective capability for a different purpose). "Responsive layout
issues" and "mobile content accessibility" beyond what's directly
declared in the viewport meta tag would need actual visual/rendering
analysis this module doesn't do; claiming to detect them from raw HTML
alone would be exactly the kind of fabricated signal this codebase's
rule engine never produces.
"""

from __future__ import annotations

import uuid

from app.models.page_snapshot import PageSnapshot
from app.models.seo_finding import FindingSeverity
from app.seo_rules.types import FindingCandidate

# Google's own stated expectation for a responsive viewport
# (developers.google.com/search/mobile-sites/mobile-seo/responsive-design):
# width keyed to the device, not a fixed pixel value.
_RESPONSIVE_WIDTH_TOKEN = "width=device-width"


def check(page_id: uuid.UUID, snapshot: PageSnapshot) -> list[FindingCandidate]:
    candidates: list[FindingCandidate] = []

    if not snapshot.viewport_content:
        candidates.append(
            FindingCandidate(
                page_id=page_id,
                rule_code="MOBILE_VIEWPORT_MISSING",
                severity=FindingSeverity.warning,
                confidence=1.0,
                evidence={},
            )
        )
        return candidates

    normalized = snapshot.viewport_content.lower().replace(" ", "")
    if _RESPONSIVE_WIDTH_TOKEN not in normalized:
        candidates.append(
            FindingCandidate(
                page_id=page_id,
                rule_code="MOBILE_VIEWPORT_NOT_RESPONSIVE",
                severity=FindingSeverity.warning,
                confidence=0.8,
                evidence={"viewport_content": snapshot.viewport_content},
            )
        )

    return candidates
