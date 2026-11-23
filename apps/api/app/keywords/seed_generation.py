"""Seed keyword generation (SEO Growth Engine spec section 4A). Every
seed here is derived deterministically from data RankPilot already
has -- crawled page titles/headings, the site's own GSC queries, and
whatever the user typed as a business description or explicit seed
list. No AI call, no external service, nothing estimated.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.keyword_observation import KeywordObservation
from app.models.page import Page
from app.models.page_snapshot import PageSnapshot
from app.models.website import Website

MAX_SEEDS = 60
MIN_HEADING_LENGTH = 3
MAX_HEADING_LENGTH = 80

_STOPWORDS = frozenset(
    "a an and are as at be by do does for from how in is it of on or the to what when where which who why with your you this that these those".split()
)


def _topic_words(text: str | None) -> set[str]:
    """Lower-cased content words with a crude plural strip, so "stairs"
    and "stair" match. Used only to check a heading is about the page."""
    words = set()
    for raw in (text or "").lower().replace("|", " ").replace("-", " ").split():
        word = raw.strip(".,:;!?()[]\"'")
        if len(word) < 3 or word in _STOPWORDS:
            continue
        words.add(word[:-1] if word.endswith("s") and len(word) > 3 else word)
    return words


def _latest_snapshots(db: Session, website_id) -> list[PageSnapshot]:
    # One snapshot per page: the most recently fetched one for each
    # page_id, found via a correlated max(fetched_at) rather than
    # loading every historical snapshot.
    from sqlalchemy import func

    latest_ids_subquery = (
        db.query(PageSnapshot.page_id, func.max(PageSnapshot.fetched_at).label("max_fetched_at"))
        .join(Page, PageSnapshot.page_id == Page.id)
        .filter(Page.website_id == website_id)
        .group_by(PageSnapshot.page_id)
        .subquery()
    )
    return (
        db.query(PageSnapshot)
        .join(
            latest_ids_subquery,
            (PageSnapshot.page_id == latest_ids_subquery.c.page_id)
            & (PageSnapshot.fetched_at == latest_ids_subquery.c.max_fetched_at),
        )
        .all()
    )


# Where a seed came from. Only Search Console queries show that people actually search for the phrase; text found on the
# site only shows that the site says it, so the two are never given the same confidence.
ORIGIN_CONFIDENCE = {"extra": 0.8, "site_name": 0.6, "site_title": 0.5, "site_h1": 0.5, "site_heading": 0.3, "gsc_query": 1.0}
ORIGIN_LABEL = {
    "extra": "A seed you supplied.", "site_name": "Your site's name.", "site_title": "Found in a page title on your site. This shows what your site says, not that people search for it.",
    "site_h1": "Found in a main heading on your site. This shows what your site says, not that people search for it.",
    "site_heading": "Found in a section heading on your site. This shows what your site says, not that people search for it.",
    "gsc_query": "A real Search Console query for your site.",
}
# Section headings that only organise an article and are never a topic on their own.
_GENERIC_HEADINGS = frozenset(
    {"introduction", "overview", "summary", "conclusion", "faq", "faqs", "tips", "key points", "key takeaways", "takeaways", "related articles",
     "in this article", "table of contents", "what usually helps", "what to do next", "how it works", "final thoughts", "next steps"}
)


def _is_generic_heading(text: str) -> bool:
    cleaned = text.lower().strip(" .:?!")
    return cleaned in _GENERIC_HEADINGS or len(cleaned.split()) < 2


def generate_seed_details(db: Session, website: Website, *, extra_seeds: list[str] | None = None) -> list[tuple[str, str]]:
    """(seed, origin) pairs, deduplicated and length-bounded; origin is a key of ORIGIN_CONFIDENCE."""
    seeds: list[tuple[str, str]] = []
    seen: set[str] = set()

    def add(text: str | None, origin: str) -> None:
        if not text:
            return
        cleaned = text.strip()
        if not cleaned or len(cleaned) < MIN_HEADING_LENGTH or len(cleaned) > MAX_HEADING_LENGTH:
            return
        key = cleaned.lower()
        if key in seen:
            return
        seen.add(key)
        seeds.append((cleaned, origin))

    for seed in extra_seeds or []:
        add(seed, "extra")

    add(website.display_name, "site_name")

    for snapshot in _latest_snapshots(db, website.id):
        add(snapshot.title, "site_title")
        page_topic = _topic_words(snapshot.title)
        for text in snapshot.headings_json.get("h1", []):
            add(text, "site_h1")
            page_topic |= _topic_words(text)
        # Section headings ("In this article", "What usually helps") are not keywords. Keep an h2 only if it is not a generic
        # section label and is about the same topic as the page's own title/h1. Even then it only shows what the site says,
        # so it gets the lowest confidence (see ORIGIN_CONFIDENCE).
        for text in snapshot.headings_json.get("h2", []):
            if not _is_generic_heading(text) and _topic_words(text) & page_topic:
                add(text, "site_heading")
        if len(seeds) >= MAX_SEEDS:
            break

    top_queries = (
        db.query(KeywordObservation.query)
        .filter(KeywordObservation.website_id == website.id)
        .distinct()
        .limit(MAX_SEEDS)
        .all()
    )
    for (query,) in top_queries:
        add(query, "gsc_query")
        if len(seeds) >= MAX_SEEDS:
            break

    return seeds[:MAX_SEEDS]


def generate_seed_keywords(db: Session, website: Website, *, extra_seeds: list[str] | None = None) -> list[str]:
    """Returns a deduplicated, length-bounded list of candidate seed keywords built from: the website's display name, crawled
    page titles and H1/H2 headings, its own recent GSC queries, and any explicit seeds the caller passes in."""
    return [text for text, _origin in generate_seed_details(db, website, extra_seeds=extra_seeds)]
