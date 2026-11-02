"""Sitemap inclusion checks (RP-0403)."""

from __future__ import annotations

from app.models.page import Page
from app.models.seo_finding import FindingSeverity
from app.seo_rules.types import FindingCandidate


def check_sitemap_urls(
    sitemap_normalized_urls: set[str], pages_by_normalized_url: dict[str, Page]
) -> list[FindingCandidate]:
    candidates: list[FindingCandidate] = []

    for normalized_url in sitemap_normalized_urls:
        page = pages_by_normalized_url.get(normalized_url)
        if page is None:
            continue
        if (page.last_status_code or 0) >= 400:
            candidates.append(
                FindingCandidate(
                    page_id=page.id,
                    rule_code="SITEMAP_URL_ERROR",
                    severity=FindingSeverity.warning,
                    confidence=1.0,
                    evidence={"status_code": page.last_status_code},
                )
            )

    return candidates
