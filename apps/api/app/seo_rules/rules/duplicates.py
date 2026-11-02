"""Site-wide duplicate title / meta-description detection (RP-0404)."""

from __future__ import annotations

from collections import defaultdict
from uuid import UUID

from app.models.page_snapshot import PageSnapshot
from app.models.seo_finding import FindingSeverity
from app.seo_rules.types import FindingCandidate


def _find_duplicates(values_by_page: dict[UUID, str], rule_code: str) -> list[FindingCandidate]:
    groups: dict[str, list[UUID]] = defaultdict(list)
    for page_id, value in values_by_page.items():
        if value:
            groups[value].append(page_id)

    candidates: list[FindingCandidate] = []
    for value, page_ids in groups.items():
        if len(page_ids) < 2:
            continue
        for page_id in page_ids:
            others = [str(pid) for pid in page_ids if pid != page_id]
            candidates.append(
                FindingCandidate(
                    page_id=page_id,
                    rule_code=rule_code,
                    severity=FindingSeverity.warning,
                    confidence=1.0,
                    evidence={"value": value, "duplicate_page_ids": others},
                )
            )
    return candidates


def check_site(snapshots_by_page_id: dict[UUID, PageSnapshot]) -> list[FindingCandidate]:
    titles = {page_id: s.title for page_id, s in snapshots_by_page_id.items()}
    descriptions = {page_id: s.meta_description for page_id, s in snapshots_by_page_id.items()}

    return _find_duplicates(titles, "DUPLICATE_TITLE") + _find_duplicates(
        descriptions, "DUPLICATE_META_DESCRIPTION"
    )
