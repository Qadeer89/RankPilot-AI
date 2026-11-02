"""Sitemap discovery and parsing (RP-0301).

Supports plain <urlset> sitemaps and one level of <sitemapindex> nesting,
bounded so a hostile or oversized sitemap can't blow the crawl budget.
"""

from __future__ import annotations

from urllib.parse import urljoin
from xml.etree import ElementTree

from app.crawler.fetch import FetchError, safe_fetch

MAX_SITEMAP_FILES = 10
MAX_URLS_PER_SITEMAP = 5000

_NAMESPACE = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}


def _parse_sitemap_xml(body: str) -> tuple[list[str], list[str]]:
    """Return (page_urls, nested_sitemap_urls) from one sitemap document."""
    try:
        root = ElementTree.fromstring(body)
    except ElementTree.ParseError:
        return [], []

    tag = root.tag.rsplit("}", 1)[-1]
    if tag == "sitemapindex":
        nested = [
            loc.text.strip()
            for loc in root.findall("sm:sitemap/sm:loc", _NAMESPACE)
            if loc.text
        ]
        return [], nested[:MAX_SITEMAP_FILES]

    urls = [
        loc.text.strip()
        for loc in root.findall("sm:url/sm:loc", _NAMESPACE)
        if loc.text
    ]
    return urls[:MAX_URLS_PER_SITEMAP], []


def discover_sitemap_urls(
    origin_url: str, robots_sitemap_urls: list[str], *, user_agent: str
) -> list[str]:
    """Fetch robots-declared sitemaps plus the conventional /sitemap.xml
    fallback, and return the bounded, deduplicated list of page URLs found.
    """
    candidates = list(robots_sitemap_urls) or [urljoin(origin_url, "/sitemap.xml")]

    seen_sitemaps: set[str] = set()
    page_urls: list[str] = []
    queue = candidates[:MAX_SITEMAP_FILES]

    while queue and len(seen_sitemaps) < MAX_SITEMAP_FILES:
        sitemap_url = queue.pop(0)
        if sitemap_url in seen_sitemaps:
            continue
        seen_sitemaps.add(sitemap_url)

        try:
            result = safe_fetch(sitemap_url, user_agent=user_agent)
        except FetchError:
            continue
        if result.status_code >= 400:
            continue

        urls, nested = _parse_sitemap_xml(result.body)
        page_urls.extend(urls)
        for nested_url in nested:
            if nested_url not in seen_sitemaps:
                queue.append(nested_url)

    # Deduplicate while preserving order.
    deduped: list[str] = []
    seen_pages: set[str] = set()
    for url in page_urls:
        if url not in seen_pages:
            seen_pages.add(url)
            deduped.append(url)
    return deduped
