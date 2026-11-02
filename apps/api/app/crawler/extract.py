"""HTML extraction and page normalization (RP-0303).

Pulls exactly the signals the deterministic rule engine needs: title, meta
description, canonical, robots directives, headings, structured data, and
internal links. Crawled HTML is untrusted input — this module only ever
reads it with a standard parser; it is never passed to AI or eval'd/executed
(AI_AGENT_SPECIFICATION.md #6).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from urllib.parse import urldefrag, urljoin, urlsplit

from bs4 import BeautifulSoup


@dataclass(frozen=True)
class StructuredDataBlock:
    raw: str
    parsed: dict | list | None
    parse_error: str | None


@dataclass(frozen=True)
class PageExtraction:
    title: str | None
    meta_description: str | None
    canonical_url: str | None
    meta_robots_directives: list[str]
    headings: dict[str, list[str]] = field(default_factory=dict)
    structured_data: list[StructuredDataBlock] = field(default_factory=list)
    internal_links: list[str] = field(default_factory=list)
    content_fingerprint: str = ""


def _normalize_link(href: str, base_url: str, site_hostname: str) -> str | None:
    href = href.strip()
    if not href or href.startswith(("mailto:", "tel:", "javascript:")):
        return None
    absolute = urljoin(base_url, href)
    absolute, _fragment = urldefrag(absolute)
    parts = urlsplit(absolute)
    if parts.scheme not in ("http", "https"):
        return None
    if parts.hostname != site_hostname:
        return None
    return absolute


def extract_page(html: str, *, base_url: str, site_hostname: str) -> PageExtraction:
    soup = BeautifulSoup(html, "lxml")

    title_tag = soup.find("title")
    title = title_tag.get_text(strip=True) if title_tag else None

    meta_description_tag = soup.find("meta", attrs={"name": "description"})
    meta_description = (
        meta_description_tag.get("content", "").strip() if meta_description_tag else None
    ) or None

    canonical_tag = soup.find("link", attrs={"rel": "canonical"})
    canonical_url = canonical_tag.get("href", "").strip() if canonical_tag else None
    if canonical_url:
        canonical_url = urljoin(base_url, canonical_url)

    robots_tag = soup.find("meta", attrs={"name": "robots"})
    robots_content = robots_tag.get("content", "") if robots_tag else ""
    meta_robots_directives = [d.strip().lower() for d in robots_content.split(",") if d.strip()]

    headings: dict[str, list[str]] = {}
    for level in range(1, 7):
        tag_name = f"h{level}"
        texts = [h.get_text(strip=True) for h in soup.find_all(tag_name)]
        if texts:
            headings[tag_name] = texts

    structured_data: list[StructuredDataBlock] = []
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = script.get_text()
        try:
            parsed = json.loads(raw)
            structured_data.append(StructuredDataBlock(raw=raw, parsed=parsed, parse_error=None))
        except json.JSONDecodeError as exc:
            structured_data.append(StructuredDataBlock(raw=raw, parsed=None, parse_error=str(exc)))

    internal_links: list[str] = []
    seen_links: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        normalized = _normalize_link(anchor["href"], base_url, site_hostname)
        if normalized and normalized not in seen_links:
            seen_links.add(normalized)
            internal_links.append(normalized)

    visible_text = soup.get_text(separator=" ", strip=True)
    content_fingerprint = hashlib.sha256(visible_text.encode("utf-8")).hexdigest()

    return PageExtraction(
        title=title,
        meta_description=meta_description,
        canonical_url=canonical_url,
        meta_robots_directives=meta_robots_directives,
        headings=headings,
        structured_data=structured_data,
        internal_links=internal_links,
        content_fingerprint=content_fingerprint,
    )
