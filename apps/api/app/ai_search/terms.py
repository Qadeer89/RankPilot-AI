"""Tiny, dependency-free term matching used to compare a query with page text."""

from __future__ import annotations

import re

STOPWORDS = frozenset(
    "a an the and or of to in on at for from by with without is are was were be been being do does did can could should would will may might "
    "i my me we our you your it its this that these those as if then than so not no how what why which where when who whom whose "
    "best top near vs versus about into over under after before between".split()
)
_WORD = re.compile(r"[\w']+", re.UNICODE)


def stem(word: str) -> str:
    w = word.lower().strip("'")
    for suffix in ("ing", "es", "ed", "s"):
        if len(w) > len(suffix) + 3 and w.endswith(suffix):
            return w[: -len(suffix)]
    return w


def content_terms(text: str) -> set[str]:
    return {stem(w) for w in _WORD.findall(text.lower()) if w not in STOPWORDS and len(w) > 1}


def coverage(query: str, text: str) -> float:
    """Share of the query's meaningful terms that appear in `text` (0..1). 1.0 for an empty query."""
    needed = content_terms(query)
    if not needed:
        return 1.0
    return len(needed & content_terms(text)) / len(needed)
