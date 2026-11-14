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
class ImageExtraction:
    src: str | None
    alt_text: str | None
    has_alt: bool
    is_decorative: bool
    has_dimensions: bool


@dataclass(frozen=True)
class ExternalLinkExtraction:
    url: str
    is_nofollow: bool
    is_sponsored: bool
    is_ugc: bool


@dataclass(frozen=True)
class PageExtraction:
    title: str | None
    meta_description: str | None
    canonical_url: str | None
    meta_robots_directives: list[str]
    headings: dict[str, list[str]] = field(default_factory=dict)
    structured_data: list[StructuredDataBlock] = field(default_factory=list)
    internal_links: list[str] = field(default_factory=list)
    external_links: list[ExternalLinkExtraction] = field(default_factory=list)
    images: list[ImageExtraction] = field(default_factory=list)
    content_fingerprint: str = ""
    word_count: int = 0


def _absolute_http_url(href: str, base_url: str) -> str | None:
    href = href.strip()
    if not href or href.startswith(("mailto:", "tel:", "javascript:")):
        return None
    absolute = urljoin(base_url, href)
    absolute, _fragment = urldefrag(absolute)
    parts = urlsplit(absolute)
    if parts.scheme not in ("http", "https"):
        return None
    return absolute


def _normalize_link(href: str, base_url: str, site_hostname: str) -> str | None:
    absolute = _absolute_http_url(href, base_url)
    if absolute is None:
        return None
    parts = urlsplit(absolute)
    if parts.hostname != site_hostname:
        return None
    # Cloudflare rewrites a mailto: href server-side into /cdn-cgi/l/email-
    # protection#<hash> (JS-only, decoded client-side), so the mailto:
    # check above never sees it -- it looks like a same-site page and gets
    # crawled, where it has no real content to fetch and reliably errors.
    if parts.path.startswith("/cdn-cgi/"):
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
    external_links: list[ExternalLinkExtraction] = []
    seen_internal: set[str] = set()
    seen_external: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        normalized = _normalize_link(anchor["href"], base_url, site_hostname)
        if normalized is not None:
            if normalized not in seen_internal:
                seen_internal.add(normalized)
                internal_links.append(normalized)
            continue

        # Not an internal link -- but it might still be a same-hostname
        # link _normalize_link deliberately excluded (the cdn-cgi email-
        # obfuscation case above), which must never be miscounted as
        # external either.
        absolute = _absolute_http_url(anchor["href"], base_url)
        if absolute is None:
            continue
        if urlsplit(absolute).hostname == site_hostname:
            continue
        if absolute in seen_external:
            continue
        seen_external.add(absolute)

        rel_attr = anchor.get("rel") or []
        rel_values = rel_attr if isinstance(rel_attr, list) else rel_attr.split()
        rel_values = [v.lower() for v in rel_values]
        external_links.append(
            ExternalLinkExtraction(
                url=absolute,
                is_nofollow="nofollow" in rel_values,
                is_sponsored="sponsored" in rel_values,
                is_ugc="ugc" in rel_values,
            )
        )

    images: list[ImageExtraction] = []
    for img in soup.find_all("img"):
        has_src = img.has_attr("src") and img["src"].strip()
        src = urljoin(base_url, img["src"].strip()) if has_src else None
        has_alt = img.has_attr("alt")
        alt_text = img.get("alt", "").strip() if has_alt else None
        is_decorative = has_alt and alt_text == ""
        has_dimensions = bool(img.get("width")) and bool(img.get("height"))
        images.append(
            ImageExtraction(
                src=src,
                alt_text=alt_text or None,
                has_alt=has_alt,
                is_decorative=is_decorative,
                has_dimensions=has_dimensions,
            )
        )

    # Measure "content" from <body> only, with script/style text
    # stripped first -- otherwise the <title> (already compared
    # separately via DUPLICATE_TITLE) would bleed into the fingerprint,
    # and a shared analytics snippet or CSS block would inflate the word
    # count, either way undermining thin-content and duplicate-body-
    # content detection's whole point (app/seo_rules/rules/content.py).
    content_root = soup.body or soup
    for tag in content_root.find_all(("script", "style")):
        tag.decompose()
    visible_text = content_root.get_text(separator=" ", strip=True)
    content_fingerprint = hashlib.sha256(visible_text.encode("utf-8")).hexdigest()
    word_count = len(visible_text.split())

    return PageExtraction(
        title=title,
        meta_description=meta_description,
        canonical_url=canonical_url,
        meta_robots_directives=meta_robots_directives,
        headings=headings,
        structured_data=structured_data,
        internal_links=internal_links,
        external_links=external_links,
        images=images,
        content_fingerprint=content_fingerprint,
        word_count=word_count,
    )
