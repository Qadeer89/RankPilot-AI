"""Image SEO/accessibility checks (RankPilot AI Phase 2 "Image SEO Audit").

Operates on PageImage rows persisted for the page's current crawl
(app/crawler/orchestrator.py:_sync_page_images) -- never on live HTTP
fetches of the images themselves, matching the rest of this engine's
"only flag what we can verify from data we already have" rule (see
links.py's broken-link check, which only cross-references already-crawled
pages rather than fetching new URLs).
"""

from __future__ import annotations

import re
from uuid import UUID

from app.models.page import Page
from app.models.page_image import PageImage
from app.models.seo_finding import FindingSeverity
from app.seo_rules.types import FindingCandidate

# Filename-shaped alt text ("IMG_1234.jpg", "dsc00421", "photo-2") tells a
# screen-reader user or search engine nothing a filename didn't already
# say -- a common CMS default that looks like real alt text but isn't.
_FILENAME_LIKE_ALT = re.compile(
    r"^(img|image|dsc|photo|picture|screenshot)[-_\s]?\d+$", re.IGNORECASE
)
_FILE_EXTENSION_SUFFIX = re.compile(r"\.(jpe?g|png|gif|webp|svg|bmp|avif)$", re.IGNORECASE)


def _is_unhelpful_alt_text(alt_text: str) -> bool:
    stripped = alt_text.strip()
    if _FILE_EXTENSION_SUFFIX.search(stripped):
        return True
    return bool(_FILENAME_LIKE_ALT.match(stripped))


def check(page_id: UUID, page_images: list[PageImage]) -> list[FindingCandidate]:
    candidates: list[FindingCandidate] = []
    if not page_images:
        return candidates

    missing_src = [img for img in page_images if not img.image_src]
    if missing_src:
        candidates.append(
            FindingCandidate(
                page_id,
                "IMAGE_MISSING_SRC",
                FindingSeverity.critical,
                1.0,
                {"count": len(missing_src)},
            )
        )

    missing_alt = [
        img for img in page_images if img.image_src and not img.has_alt
    ]
    if missing_alt:
        candidates.append(
            FindingCandidate(
                page_id,
                "IMAGE_MISSING_ALT",
                FindingSeverity.warning,
                1.0,
                {"count": len(missing_alt), "images": [img.image_src for img in missing_alt][:20]},
            )
        )

    unhelpful = [
        img
        for img in page_images
        if img.image_src
        and img.has_alt
        and not img.is_decorative
        and img.alt_text
        and _is_unhelpful_alt_text(img.alt_text)
    ]
    if unhelpful:
        candidates.append(
            FindingCandidate(
                page_id,
                "IMAGE_UNHELPFUL_ALT_TEXT",
                FindingSeverity.info,
                0.7,
                {
                    "count": len(unhelpful),
                    "images": [
                        {"src": img.image_src, "alt_text": img.alt_text} for img in unhelpful
                    ][:20],
                },
            )
        )

    missing_dimensions = [
        img for img in page_images if img.image_src and not img.has_dimensions
    ]
    if missing_dimensions:
        candidates.append(
            FindingCandidate(
                page_id,
                "IMAGE_MISSING_DIMENSIONS",
                FindingSeverity.info,
                0.6,
                {"count": len(missing_dimensions)},
            )
        )

    return candidates


def check_broken_images(
    pages_by_normalized_url: dict[str, Page],
    page_images_by_page_id: dict[UUID, list[PageImage]],
    normalize_url,
) -> list[FindingCandidate]:
    """Flags an <img src> that itself resolves to a page this site already
    crawled and knows returned an error status -- the same-site-only,
    never-fetch-something-new approach links.check_broken_links uses.

    Most <img> src values are media files, not crawled pages, so this only
    catches the subset of broken images we can verify without a new
    network request; it is not a general-purpose image health check.
    """
    candidates: list[FindingCandidate] = []
    for page_id, images in page_images_by_page_id.items():
        broken = []
        for image in images:
            if not image.image_src:
                continue
            target_page = pages_by_normalized_url.get(normalize_url(image.image_src))
            if target_page is not None and (target_page.last_status_code or 0) >= 400:
                broken.append({"src": image.image_src, "status_code": target_page.last_status_code})
        if broken:
            candidates.append(
                FindingCandidate(
                    page_id=page_id,
                    rule_code="IMAGE_BROKEN",
                    severity=FindingSeverity.warning,
                    confidence=1.0,
                    evidence={"broken_images": broken},
                )
            )
    return candidates
