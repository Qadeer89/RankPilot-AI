"""Deterministic internal-link candidate generation (the crawled site
graph half of the Internal Linking Analyst,
AI_AGENT_SPECIFICATION.md #2 item 3: "identifies relevant source/target
page candidates from the crawled site graph"). Determining *which pages
exist and roughly how related they are* is deterministic; only explaining
the relevance in natural language is AI's job (app/ai/internal_linking.py).
"""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.models.page import Page
from app.models.page_snapshot import PageSnapshot
from app.models.seo_finding import FindingStatus, SEOFinding
from app.models.website import Website

_STOPWORDS = {
    "the", "a", "an", "of", "for", "and", "to", "in", "on", "with", "is",
    "your", "how", "what", "why", "at", "by", "it", "this", "that", "or",
}
MIN_WORD_LENGTH = 3


def _title_words(title: str | None) -> set[str]:
    if not title:
        return set()
    words = {w.lower().strip(".,:;!?()\"'") for w in title.split()}
    return {w for w in words if len(w) >= MIN_WORD_LENGTH and w not in _STOPWORDS}


def _latest_snapshot_by_page(db: Session, website_id: uuid.UUID) -> dict[uuid.UUID, PageSnapshot]:
    rows = (
        db.query(PageSnapshot)
        .join(Page, PageSnapshot.page_id == Page.id)
        .filter(Page.website_id == website_id)
        .order_by(PageSnapshot.fetched_at.asc())
        .all()
    )
    latest: dict[uuid.UUID, PageSnapshot] = {}
    for snapshot in rows:
        latest[snapshot.page_id] = snapshot  # ascending order: last write is latest
    return latest


def find_orphan_target_pages(db: Session, website: Website) -> list[Page]:
    """Pages with an open ORPHAN_PAGE_CANDIDATE finding — the targets this
    analyst tries to find new internal links for.
    """
    page_ids = (
        db.query(SEOFinding.page_id)
        .filter(
            SEOFinding.website_id == website.id,
            SEOFinding.rule_code == "ORPHAN_PAGE_CANDIDATE",
            SEOFinding.status == FindingStatus.open,
            SEOFinding.page_id.isnot(None),
        )
        .all()
    )
    ids = [row[0] for row in page_ids]
    if not ids:
        return []
    return db.query(Page).filter(Page.id.in_(ids)).all()


def find_candidate_sources(
    db: Session, website: Website, target_page: Page, *, limit: int = 5
) -> list[tuple[Page, PageSnapshot]]:
    """Rank other crawled pages by title-word overlap with the target page
    as a cheap relevance proxy; the AI agent explains (and can override)
    the final pick from this shortlist, it doesn't search the whole site
    itself.
    """
    snapshots_by_page = _latest_snapshot_by_page(db, website.id)
    target_snapshot = snapshots_by_page.get(target_page.id)
    target_words = _title_words(target_snapshot.title if target_snapshot else None)

    scored: list[tuple[int, uuid.UUID, PageSnapshot]] = []
    for page_id, snapshot in snapshots_by_page.items():
        if page_id == target_page.id:
            continue
        overlap = len(target_words & _title_words(snapshot.title))
        scored.append((overlap, page_id, snapshot))

    # Highest overlap first; stable fallback to most-recently-fetched when tied.
    scored.sort(key=lambda t: (t[0], t[2].fetched_at), reverse=True)
    top = scored[:limit]

    pages_by_id = {p.id: p for p in db.query(Page).filter(Page.website_id == website.id).all()}
    return [(pages_by_id[page_id], snapshot) for _overlap, page_id, snapshot in top if page_id in pages_by_id]
