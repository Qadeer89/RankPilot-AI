"""Splits a document's text into retrievable chunks for embedding."""

from __future__ import annotations


def chunk_text(text: str, *, max_chars: int, overlap_chars: int) -> list[str]:
    """Split on paragraph boundaries first, then pack paragraphs into
    chunks up to `max_chars`, carrying the last `overlap_chars` of a
    chunk into the next one so an answer that straddles a boundary
    isn't lost to either side.
    """
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    if not paragraphs:
        return []

    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        candidate = f"{current}\n\n{paragraph}" if current else paragraph
        if len(candidate) <= max_chars:
            current = candidate
            continue

        if current:
            chunks.append(current)
            current = current[-overlap_chars:] + "\n\n" + paragraph if overlap_chars else paragraph
        else:
            current = paragraph

        # A single paragraph longer than max_chars on its own: hard-split it.
        while len(current) > max_chars:
            chunks.append(current[:max_chars])
            current = current[max_chars - overlap_chars :] if overlap_chars else current[max_chars:]

    if current:
        chunks.append(current)

    return chunks
