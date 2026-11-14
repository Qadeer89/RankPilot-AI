"""JavaScript-rendering checks (RankPilot AI Phase 4 "Advanced Crawling
& Performance Intelligence").

Operates only on a PageRenderResult that app/crawler/render.py's
narrow heuristic actually attempted -- a page that never looked
JS-dependent has no row here and produces no finding either way,
never a fabricated "passed" verdict for a check that wasn't run.
"""

from __future__ import annotations

from uuid import UUID

from app.models.page_render_result import PageRenderResult, RenderStatus
from app.models.seo_finding import FindingSeverity
from app.seo_rules.types import FindingCandidate

# A deliberate judgment call, not a precise measurement: rendered
# content meaningfully exceeding what the raw HTML offers suggests a
# search crawler relying only on raw HTML would see substantially less
# than what's actually on the page.
CONTENT_GAP_RATIO_THRESHOLD = 2.0
MIN_RENDERED_WORD_COUNT_FOR_GAP_CHECK = 20


def check(page_id: UUID, render_result: PageRenderResult | None) -> list[FindingCandidate]:
    candidates: list[FindingCandidate] = []
    if render_result is None:
        return candidates

    if render_result.render_status == RenderStatus.failed:
        candidates.append(
            FindingCandidate(
                page_id=page_id,
                rule_code="RENDER_FAILURE",
                severity=FindingSeverity.warning,
                confidence=0.8,
                evidence={"error": render_result.error_message},
            )
        )
        return candidates

    rendered = render_result.rendered_word_count or 0
    if rendered < MIN_RENDERED_WORD_COUNT_FOR_GAP_CHECK:
        return candidates

    raw = max(render_result.raw_word_count, 1)
    ratio = rendered / raw
    if ratio >= CONTENT_GAP_RATIO_THRESHOLD:
        candidates.append(
            FindingCandidate(
                page_id=page_id,
                rule_code="JS_RENDERING_CONTENT_GAP",
                severity=FindingSeverity.warning,
                confidence=0.6,
                evidence={
                    "raw_word_count": render_result.raw_word_count,
                    "rendered_word_count": render_result.rendered_word_count,
                    "ratio": round(ratio, 2),
                },
            )
        )

    return candidates
