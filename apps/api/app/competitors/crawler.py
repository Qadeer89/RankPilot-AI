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

import time
from dataclasses import dataclass
from urllib.parse import urlsplit

from app.crawler.extract import extract_page
from app.crawler.fetch import DEFAULT_USER_AGENT, FetchError, FetchResult, safe_fetch
from app.crawler.robots import RobotsPolicy, fetch_robots_policy

MAX_PAGES_PER_DOMAIN = 5

# Politeness and bounds. This runs against someone else's server inside a
# web request, so it is slower and stricter than crawling an owned site.
MIN_REQUEST_DELAY_SECONDS = 1.0
MAX_CRAWL_DELAY_SECONDS = 10.0  # a robots.txt Crawl-delay above this is capped
MAX_TOTAL_SECONDS = 60.0  # hard stop for one domain
RETRY_STATUS_CODES = frozenset({429, 502, 503, 504})
MAX_RETRY_WAIT_SECONDS = 5.0
DEFAULT_RETRY_WAIT_SECONDS = 1.5

_sleep = time.sleep  # indirection so tests do not really wait
_monotonic = time.monotonic


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


def _same_site(host_a: str | None, host_b: str | None) -> bool:
    """`example.com` and `www.example.com` are the same site; anything
    else (a redirect to a different domain) is not followed into."""
    def strip(host: str | None) -> str:
        host = (host or "").lower()
        return host[4:] if host.startswith("www.") else host

    return strip(host_a) == strip(host_b) and bool(strip(host_a))


def _failed(url: str, error: str) -> CompetitorPageResult:
    return CompetitorPageResult(
        url=url, title=None, meta_description=None, headings={}, word_count=0, has_structured_data=False, error=error
    )


def _retry_wait(result: FetchResult | None) -> float:
    if result is not None:
        raw = result.headers.get("retry-after", "")
        if raw.strip().isdigit():
            return min(float(raw), MAX_RETRY_WAIT_SECONDS)
    return DEFAULT_RETRY_WAIT_SECONDS


def _fetch_with_one_retry(url: str) -> FetchResult:
    """One retry, and only for failures that are plausibly transient: a
    timeout or connection error, or 429/502/503/504 (honouring a short
    Retry-After). An SSRF block, an oversize response or a redirect loop
    is never retried.
    """
    try:
        result = safe_fetch(url, preserve_query=True)
    except FetchError as exc:
        if not str(exc).startswith("Request failed"):
            raise
        _sleep(DEFAULT_RETRY_WAIT_SECONDS)
        return safe_fetch(url, preserve_query=True)
    if result.status_code in RETRY_STATUS_CODES:
        _sleep(_retry_wait(result))
        return safe_fetch(url, preserve_query=True)
    return result


def fetch_competitor_pages(domain: str, *, max_pages: int = MAX_PAGES_PER_DOMAIN) -> list[CompetitorPageResult]:
    """Fetches the competitor's homepage, then up to `max_pages - 1` of
    its own same-domain links found there -- a lightweight sample, not
    a full site crawl, out of politeness and cost (this runs on
    someone else's server, unlike crawling the user's own verified
    site). Every page is robots.txt-checked before fetching, and
    anything that does not yield usable content (blocked by robots.txt,
    HTTP error, not HTML, timeout, no server-rendered content) is still
    returned, with `error` saying why, rather than silently dropped.

    Pages are read as the server returns them: JavaScript is not
    executed for competitor sites, so a page that only renders in a
    browser is reported as such rather than guessed at.
    """
    homepage_url = _homepage_url(domain)
    hostname = urlsplit(homepage_url).hostname or domain
    started = _monotonic()

    robots_by_host: dict[str, RobotsPolicy | None] = {}

    def _robots_for(url: str) -> RobotsPolicy | None:
        host = urlsplit(url).netloc.lower()
        if host not in robots_by_host:
            try:
                robots_by_host[host] = fetch_robots_policy(url, user_agent=DEFAULT_USER_AGENT)
            except FetchError:
                robots_by_host[host] = None
        return robots_by_host[host]

    def _allowed(url: str) -> bool:
        policy = _robots_for(url)
        return policy is None or policy.can_fetch(url, DEFAULT_USER_AGENT)

    def _delay(url: str) -> float:
        policy = _robots_for(url)
        crawl_delay = policy.crawl_delay(DEFAULT_USER_AGENT) if policy is not None else None
        return min(max(MIN_REQUEST_DELAY_SECONDS, crawl_delay or 0.0), MAX_CRAWL_DELAY_SECONDS)

    results: list[CompetitorPageResult] = []
    visited: set[str] = set()
    queue = [homepage_url]
    fetched_any = False

    while queue and len(results) < max_pages:
        if _monotonic() - started > MAX_TOTAL_SECONDS:
            results.append(_failed(queue[0], f"Stopped after {int(MAX_TOTAL_SECONDS)}s to stay polite."))
            break
        url = queue.pop(0)
        if url in visited:
            continue
        visited.add(url)

        if not _allowed(url):
            results.append(_failed(url, "Blocked by this site's robots.txt."))
            continue

        if fetched_any:
            _sleep(_delay(url))
        try:
            fetched = _fetch_with_one_retry(url)
        except FetchError as exc:
            results.append(_failed(url, str(exc)))
            continue
        fetched_any = True

        if fetched.status_code >= 400:
            results.append(_failed(fetched.final_url, f"HTTP {fetched.status_code}"))
            continue
        content_type = fetched.headers.get("content-type", "").lower()
        if content_type and "html" not in content_type:
            results.append(_failed(fetched.final_url, f"Not an HTML page (content type {content_type.split(';')[0]})."))
            continue

        final_host = urlsplit(fetched.final_url).hostname
        extraction = extract_page(
            fetched.body,
            base_url=fetched.final_url,
            site_hostname=final_host if _same_site(final_host, hostname) else hostname,
        )
        if not extraction.title and not any(extraction.headings.values()):
            results.append(
                _failed(
                    fetched.final_url,
                    "Little server-rendered content. The page may rely on JavaScript, which is not run for competitor sites.",
                )
            )
            continue
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
