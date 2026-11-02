"""Robots.txt discovery and parsing (RP-0301, WEBSITE_CONNECTORS.md #2)."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

from protego import Protego

from app.crawler.fetch import FetchError, safe_fetch


@dataclass(frozen=True)
class RobotsPolicy:
    sitemap_urls: list[str]
    _parser: Protego | None

    def can_fetch(self, url: str, user_agent: str) -> bool:
        if self._parser is None:
            return True
        return self._parser.can_fetch(url, user_agent)


def fetch_robots_policy(origin_url: str, *, user_agent: str) -> RobotsPolicy:
    """Fetch and parse robots.txt for the origin of `origin_url`.

    A missing or unreadable robots.txt is treated as "allow everything" per
    the standard convention — robots.txt absence is not itself a safety
    concern, only a courtesy signal.
    """
    parts = urlsplit(origin_url)
    robots_url = urljoin(f"{parts.scheme}://{parts.netloc}", "/robots.txt")

    try:
        result = safe_fetch(robots_url, user_agent=user_agent)
    except FetchError:
        return RobotsPolicy(sitemap_urls=[], _parser=None)

    if result.status_code >= 400:
        return RobotsPolicy(sitemap_urls=[], _parser=None)

    parser = Protego.parse(result.body)
    return RobotsPolicy(sitemap_urls=list(parser.sitemaps), _parser=parser)
