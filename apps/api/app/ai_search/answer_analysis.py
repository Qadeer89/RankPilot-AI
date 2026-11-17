"""Does the page already answer the query? A deterministic first pass, so the AI is asked only what a
person still needs to decide, and so the verdict never depends on a model's mood."""

from __future__ import annotations

from app.ai_search.page_content import Block, PageContent
from app.ai_search.terms import coverage

ANSWERED, PARTIAL, MISSING, UNKNOWN = "answered", "partial", "missing", "unknown"
HEADING_MATCH = 0.6
BODY_MENTION = 0.8
ANSWER_MIN_WORDS, ANSWER_MAX_WORDS = 20, 140


def _answer_paragraph(block: Block) -> str | None:
    for paragraph in block.paragraphs:
        n = len(paragraph.split())
        if ANSWER_MIN_WORDS <= n <= ANSWER_MAX_WORDS:
            return paragraph
    return None


def analyse_answer(query: str, content: PageContent) -> dict:
    if not content.available:
        return {"level": UNKNOWN, "reason": content.error or "The page content could not be read.", "matching_heading": None,
                "answer_excerpt": None, "title_coverage": None, "body_coverage": None, "missing_terms": []}
    title_cov = coverage(query, f"{content.title or ''} {content.meta_description or ''}")
    body_cov = coverage(query, content.text)
    best: tuple[float, Block] | None = None
    for block in content.blocks:
        if block.heading:
            score = coverage(query, block.heading)
            if best is None or score > best[0]:
                best = (score, block)
    matching = best[1] if best and best[0] >= HEADING_MATCH else None
    excerpt = _answer_paragraph(matching) if matching else None
    if matching and excerpt:
        level, reason = ANSWERED, "A section headed to match the query contains a concise answer paragraph."
    elif matching or body_cov >= BODY_MENTION:
        level = PARTIAL
        reason = ("A matching section exists but has no concise answer paragraph." if matching
                  else "The query's terms appear in the text but no section is dedicated to answering it.")
    else:
        level, reason = MISSING, "The page text does not cover most of the query's terms."
    from app.ai_search.terms import content_terms

    present = content_terms(content.text)
    missing = sorted(t for t in content_terms(query) if t not in present)
    return {"level": level, "reason": reason, "matching_heading": matching.heading if matching else None,
            "answer_excerpt": excerpt, "title_coverage": round(title_cov, 2), "body_coverage": round(body_cov, 2), "missing_terms": missing}
