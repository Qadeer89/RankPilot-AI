"""Which AI crawlers a site's robots.txt lets in. A checkable fact, shown as information: blocking an AI
crawler is a legitimate business choice, so nothing here is a "problem" by itself.

The crawler list and its roles follow claude-seo's `agentic_check.py` (https://github.com/AgriciDaniel/claude-seo,
MIT License, Copyright (c) 2026 agricidaniel); the logic is written for RankPilot. Vendors change their crawlers
and documentation: confirm with each vendor before acting on a row.

Limits: this reads robots.txt only. A firewall, CDN bot rule or login wall can block a crawler that robots.txt
allows, and RankPilot does not impersonate those crawlers to test it."""

from __future__ import annotations

from urllib.parse import urljoin, urlsplit

from protego import Protego

from app.crawler.fetch import FetchError, safe_fetch

# token, vendor, role
AI_CRAWLERS: tuple[tuple[str, str, str], ...] = (
    ("OAI-SearchBot", "OpenAI", "search"),
    ("GPTBot", "OpenAI", "training"),
    ("ChatGPT-User", "OpenAI", "user"),
    ("Claude-SearchBot", "Anthropic", "search"),
    ("ClaudeBot", "Anthropic", "training"),
    ("Claude-User", "Anthropic", "user"),
    ("PerplexityBot", "Perplexity", "search"),
    ("Perplexity-User", "Perplexity", "user"),
    ("Google-Extended", "Google", "control"),
    ("Applebot-Extended", "Apple", "control"),
    ("CCBot", "Common Crawl", "training"),
)
ROLE_MEANING = {
    "search": "indexes pages so an AI search product can find and cite them",
    "training": "collects content to train models",
    "user": "fetches a page when a person asks an assistant to",
    "control": "a robots.txt control token for AI training, not a separate crawler",
}
BASELINE = (("Googlebot", "Google", "baseline"), ("Bingbot", "Microsoft", "baseline"))
NOTE = ("robots.txt only: a firewall, CDN bot rule or login wall can still block a crawler that robots.txt allows. "
        "Blocking AI crawlers is your choice; it is shown for information, and nothing here guarantees AI visibility.")


def evaluate(robots_text: str | None, origin: str, sample_url: str | None = None) -> list[dict]:
    """robots_text None means "could not be read" (unknown), "" means no rules (everything allowed)."""
    parser = Protego.parse(robots_text) if robots_text else None
    rows = []
    for token, vendor, role in (*BASELINE, *AI_CRAWLERS):
        if robots_text is None:
            state, note = "unknown", "robots.txt could not be read right now"
        elif parser is None:
            state, note = "allowed", "no robots.txt rules"
        else:
            root_ok = parser.can_fetch(origin.rstrip("/") + "/", token)
            page_ok = parser.can_fetch(sample_url, token) if sample_url else root_ok
            state = "allowed" if root_ok and page_ok else "blocked" if not root_ok and not page_ok else "partly_blocked"
            note = {"allowed": "allowed", "blocked": "disallowed by robots.txt", "partly_blocked": "some paths are disallowed"}[state]
        rows.append({"token": token, "vendor": vendor, "role": role, "meaning": ROLE_MEANING.get(role, "a normal search crawler"), "state": state, "note": note})
    return rows


def fetch_robots_text(origin_url: str) -> tuple[str | None, str | None]:
    """(text, problem). 4xx other than 429 means "no robots.txt" (everything allowed, RFC 9309); 429/5xx/network is unknown."""
    parts = urlsplit(origin_url)
    robots_url = urljoin(f"{parts.scheme}://{parts.netloc}", "/robots.txt")
    try:
        result = safe_fetch(robots_url)
    except FetchError as exc:
        return None, str(exc)
    if result.status_code == 429 or result.status_code >= 500:
        return None, f"robots.txt answered HTTP {result.status_code}"
    if result.status_code >= 400:
        return "", None
    return result.body, None


def summarise(rows: list[dict]) -> dict:
    search = [r for r in rows if r["role"] == "search"]
    blocked_search = [r["token"] for r in search if r["state"] in ("blocked", "partly_blocked")]
    training_blocked = [r["token"] for r in rows if r["role"] in ("training", "control") and r["state"] in ("blocked", "partly_blocked")]
    unknown = all(r["state"] == "unknown" for r in rows)
    return {"search_crawlers_blocked": blocked_search, "training_crawlers_blocked": training_blocked, "unknown": unknown}


def check(origin_url: str, sample_url: str | None = None) -> dict:
    text, problem = fetch_robots_text(origin_url)
    rows = evaluate(text, origin_url, sample_url)
    return {"rows": rows, "summary": summarise(rows), "problem": problem, "note": NOTE}
