"""Performance recommendation checks (RankPilot AI Phase 4
"Performance Recommendations").

Surfaces Lighthouse's own "opportunity" audits (large images, image
formats, unnecessary JavaScript, render-blocking resources, CSS
optimization, slow-loading resources) -- re-reported, not a RankPilot
judgment call. There is no connector operation that can act on most of
these (minifying CSS/JS or converting image formats requires changing
build output, not a page's metadata), so this is report-only; where a
genuine connection to an existing AI fix capability exists (none of
these map to set_title/set_meta_description/set_alt_text/
set_canonical/set_schema_json), it would be wired in, but none do.
"""

from __future__ import annotations

from uuid import UUID

from app.models.performance_metric import PerformanceMetric
from app.models.seo_finding import FindingSeverity
from app.seo_rules.types import FindingCandidate


def check(page_id: UUID, performance_metric: PerformanceMetric | None) -> list[FindingCandidate]:
    if performance_metric is None or not performance_metric.opportunities_json:
        return []

    return [
        FindingCandidate(
            page_id=page_id,
            rule_code="PERFORMANCE_OPTIMIZATION_OPPORTUNITY",
            severity=FindingSeverity.info,
            confidence=1.0,
            evidence={"opportunities": performance_metric.opportunities_json},
        )
    ]
