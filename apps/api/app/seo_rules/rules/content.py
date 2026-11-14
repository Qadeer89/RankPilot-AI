"""Thin-content and duplicate-body-content checks (RankPilot AI Phase 2
"Thin Content Detection").

Both are deterministic, word-count/hash-based signals; the rule engine
never asks an AI model whether content is thin or duplicated. A later
agent may analyze a THIN_CONTENT or DUPLICATE_BODY_CONTENT finding and
suggest what to add or how to differentiate the page, but nothing here
-- or anywhere downstream of it -- auto-rewrites or publishes page body
content (MASTER_SPEC.md "Global implementation rules": AI only drafts
narrow, reviewable changes, never whole-page content, for this feature).
"""

from __future__ import annotations

from collections import defaultdict
from uuid import UUID

from app.models.page_snapshot import PageSnapshot
from app.models.seo_finding import FindingSeverity
from app.seo_rules.types import FindingCandidate

# schema.org @type -> minimum word count below which the page is flagged
# as thin. These are deliberate judgment calls (a product page is
# legitimately shorter than a blog post), not a claim about any
# particular site's actual content strategy -- and only ever applied
# when the page itself declares a type via JSON-LD; absent that, "default"
# applies. This is a heuristic signal (MASTER_SPEC.md #8: "label
# heuristics separately from confirmed errors"), hence the lower
# confidence vs. e.g. TITLE_MISSING's binary presence/absence check.
THIN_CONTENT_THRESHOLDS: dict[str, int] = {
    "product": 100,
    "article": 300,
    "blogposting": 300,
    "newsarticle": 300,
    "default": 200,
}
THIN_CONTENT_CONFIDENCE = 0.6

# A page below this is empty/placeholder-grade, not just "thin" --
# excluded from duplicate-body-content detection so two blank pages
# don't generate a DUPLICATE_BODY_CONTENT finding that adds nothing past
# what THIN_CONTENT (or an unrelated crawl issue) already says.
MIN_WORD_COUNT_FOR_DUPLICATE_CHECK = 10


def _declared_page_type(snapshot: PageSnapshot) -> str:
    for block in snapshot.schema_json:
        parsed = block.get("parsed")
        candidates = parsed if isinstance(parsed, list) else [parsed]
        for candidate in candidates:
            if isinstance(candidate, dict):
                schema_type = candidate.get("@type")
                if isinstance(schema_type, str) and schema_type.lower() in THIN_CONTENT_THRESHOLDS:
                    return schema_type.lower()
    return "default"


def check_thin_content(page_id: UUID, snapshot: PageSnapshot) -> list[FindingCandidate]:
    page_type = _declared_page_type(snapshot)
    threshold = THIN_CONTENT_THRESHOLDS[page_type]
    if snapshot.word_count >= threshold:
        return []
    return [
        FindingCandidate(
            page_id=page_id,
            rule_code="THIN_CONTENT",
            severity=FindingSeverity.warning,
            confidence=THIN_CONTENT_CONFIDENCE,
            evidence={"word_count": snapshot.word_count, "threshold": threshold, "page_type": page_type},
        )
    ]


def check_duplicate_body_content(snapshots_by_page_id: dict[UUID, PageSnapshot]) -> list[FindingCandidate]:
    groups: dict[str, list[UUID]] = defaultdict(list)
    for page_id, snapshot in snapshots_by_page_id.items():
        if not snapshot.content_fingerprint:
            continue
        if snapshot.word_count < MIN_WORD_COUNT_FOR_DUPLICATE_CHECK:
            continue
        groups[snapshot.content_fingerprint].append(page_id)

    candidates: list[FindingCandidate] = []
    for fingerprint, page_ids in groups.items():
        if len(page_ids) < 2:
            continue
        for page_id in page_ids:
            others = [str(pid) for pid in page_ids if pid != page_id]
            candidates.append(
                FindingCandidate(
                    page_id=page_id,
                    rule_code="DUPLICATE_BODY_CONTENT",
                    severity=FindingSeverity.warning,
                    confidence=1.0,
                    evidence={"content_fingerprint": fingerprint, "duplicate_page_ids": others},
                )
            )
    return candidates
