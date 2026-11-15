"""Fetches a small, bounded set of a competitor's publicly accessible
pages for content-gap analysis (SEO Growth Engine spec section 4D).
Reuses the site's own crawler safety machinery verbatim -- SSRF-safe
fetching (every redirect hop re-validated), robots.txt compliance, and
the same HTML extraction the site's own crawler uses -- rather than a
parallel implementation. Only ever reads what a normal public request
would return; never authenticates, never bypasses robots.txt or a
CAPTCHA, never touches a private API.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

from app.crawler.extract import extract_page
from app.crawler.fetch import DEFAULT_USER_AGENT, FetchError, safe_fetch
from app.crawler.robots import fetch_robots_policy

MAX_PAGES_PER_DOMAIN = 5


@dataclass(frozen=True)
class CompetitorPageResult:
    url: str
    title: str | None
    meta_description: str | None
    headings: dict[str, list[str]]
    word_count: int
    has_structured_data: bool
    error: str | None = None


def _homepage_url(domain: str) -> str:
    domain = domain.strip().lower()
    if domain.startswith(("http://", "https://")):
        return domain
    return f"https://{domain}"


def fetch_competitor_pages(domain: str, *, max_pages: int = MAX_PAGES_PER_DOMAIN) -> list[CompetitorPageResult]:
    """Fetches the competitor's homepage, then up to `max_pages - 1` of
    its own same-domain links found there -- a lightweight sample, not
    a full site crawl, out of politeness and cost (this runs on
    someone else's server, unlike crawling the user's own verified
    site). Every page is robots.txt-checked before fetching; a page
    that fails to fetch is still returned, with `error` set, rather
    than silently dropped.
    """
    homepage_url = _homepage_url(domain)
    hostname = urlsplit(homepage_url).hostname or domain

    try:
        robots = fetch_robots_policy(homepage_url, user_agent=DEFAULT_USER_AGENT)
    except FetchError:
        robots = None

    def _allowed(url: str) -> bool:
        return robots is None or robots.can_fetch(url, DEFAULT_USER_AGENT)

    results: list[CompetitorPageResult] = []
    visited: set[str] = set()
    queue = [homepage_url]

    while queue and len(results) < max_pages:
        url = queue.pop(0)
        if url in visited:
            continue
        visited.add(url)

        if not _allowed(url):
            continue

        try:
            fetched = safe_fetch(url)
        except FetchError as exc:
            results.append(
                CompetitorPageResult(
                    url=url, title=None, meta_description=None, headings={}, word_count=0,
                    has_structured_data=False, error=str(exc),
                )
            )
            continue

        extraction = extract_page(fetched.body, base_url=fetched.final_url, site_hostname=hostname)
        results.append(
            CompetitorPageResult(
                url=fetched.final_url,
                title=extraction.title,
                meta_description=extraction.meta_description,
                headings=extraction.headings,
                word_count=extraction.word_count,
                has_structured_data=len(extraction.structured_data) > 0,
            )
        )

        if len(results) < max_pages:
            for link in extraction.internal_links:
                if link not in visited and link not in queue:
                    queue.append(link)

    return results
