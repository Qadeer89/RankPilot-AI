"""Deterministic, explainable classification of Search Console queries.

A query may carry several labels. The original text is never changed. Nothing here claims a query is an AI
prompt: these are ordinary Google Search queries that happen to be conversational or question-shaped."""

from __future__ import annotations

import re
from dataclasses import dataclass

QUESTION = "question"
LONG_TAIL = "long_tail"
CONVERSATIONAL = "conversational"
COMPARISON = "comparison"
PROBLEM_SOLUTION = "problem_solution"
VERY_LONG = "very_long"
CATEGORIES = (QUESTION, LONG_TAIL, CONVERSATIONAL, COMPARISON, PROBLEM_SOLUTION, VERY_LONG)

_INTERROGATIVES = {"what", "how", "why", "which", "where", "when", "who", "whom", "whose"}
_AUXILIARY_STARTS = {"is", "are", "was", "were", "can", "could", "should", "would", "does", "do", "did", "will", "may", "might", "has", "have"}
# Roman-Urdu question starters (the product's first market).
_EXTRA_STARTS = {"kya", "kaise", "kese", "kyun", "kyon", "kab", "kahan", "kitna", "kitne", "kis", "kon", "kaun"}
_PERSONAL = {"i", "my", "me", "mine", "we", "our", "us", "you", "your", "i'm", "i've", "i'd", "im"}
_COMPARISON_PATTERNS = (
    re.compile(r"\bvs\.?\b"), re.compile(r"\bversus\b"), re.compile(r"\bdifference(?:s)? between\b"),
    re.compile(r"\bcompare(?:d)?\b"), re.compile(r"\bcomparison\b"), re.compile(r"\bbetter than\b"),
    re.compile(r"\bbest\b.+\b(?:for|to|in)\b"), re.compile(r"\balternatives? to\b"),
)
_PROBLEM_PATTERNS = (
    re.compile(r"\bnot working\b"), re.compile(r"\bdoesn'?t work\b"), re.compile(r"\bwon'?t\b"), re.compile(r"\bcan'?t\b"),
    re.compile(r"\bfix(?:ing)?\b"), re.compile(r"\berror\b"), re.compile(r"\bproblems? with\b"), re.compile(r"\bissues? with\b"),
    re.compile(r"\bstruggl\w+\b"), re.compile(r"\bget rid of\b"), re.compile(r"\bhow to (?:stop|quit|overcome|deal with|avoid)\b"),
    re.compile(r"\bhelp (?:with|for|me)\b"), re.compile(r"\bways to (?:stop|reduce|overcome|treat|cope)\b"), re.compile(r"\bhow do i (?:stop|quit|get rid)\b"),
)

# Constructs Search Console's RE2 engine does not support.
_RE2_UNSUPPORTED = (
    (re.compile(r"\(\?<?[=!]"), "look-around assertions are not supported by RE2"),
    (re.compile(r"\\[1-9]"), "back-references are not supported by RE2"),
    (re.compile(r"\(\?>"), "atomic groups are not supported by RE2"),
    (re.compile(r"[*+?}]\+"), "possessive quantifiers are not supported by RE2"),
)


class InvalidRegex(ValueError):
    pass


def validate_re2_regex(pattern: str) -> re.Pattern:
    """Compiles a user-supplied pattern and rejects anything Search Console (RE2) would refuse."""
    if not pattern or len(pattern) > 500:
        raise InvalidRegex("The pattern must be between 1 and 500 characters.")
    for bad, reason in _RE2_UNSUPPORTED:
        if bad.search(pattern):
            raise InvalidRegex(f"Not valid in Search Console (RE2): {reason}.")
    try:
        return re.compile(pattern)
    except re.error as exc:
        raise InvalidRegex(f"The pattern does not compile: {exc}") from exc


@dataclass(frozen=True)
class Classification:
    categories: tuple[str, ...]
    word_count: int
    signals: tuple[str, ...]  # why each label was applied

    @property
    def is_target(self) -> bool:
        """Interesting for this feature: anything beyond a plain short keyword."""
        return bool(self.categories)


def _tokens(query: str) -> list[str]:
    return query.strip().lower().split()


def classify_query(
    query: str, *, long_tail_min_words: int = 5, long_query_regex: re.Pattern | str | None = None
) -> Classification:
    from app.config import get_settings

    settings = get_settings()
    pattern = long_query_regex if long_query_regex is not None else settings.ai_search_long_query_regex
    compiled = pattern if isinstance(pattern, re.Pattern) else validate_re2_regex(pattern)
    text = " ".join(query.strip().split())
    lower = text.lower()
    words = _tokens(text)
    n = len(words)
    categories: list[str] = []
    signals: list[str] = []
    if n == 0:
        return Classification((), 0, ())

    first = words[0].strip("\"'")
    is_question = (
        (n >= 3 and (first in _INTERROGATIVES or first in _AUXILIARY_STARTS or first in _EXTRA_STARTS))
        or lower.endswith("?")
    )
    if is_question:
        categories.append(QUESTION)
        signals.append("starts with a question word" if not lower.endswith("?") else "ends with a question mark")
    if n >= long_tail_min_words:
        categories.append(LONG_TAIL)
        signals.append(f"{n} words (minimum {long_tail_min_words})")
    personal = any(w.strip(".,!?\"'") in _PERSONAL for w in words)
    if n >= 6 and (is_question or personal):
        categories.append(CONVERSATIONAL)
        signals.append("natural-language phrasing" + (" with first/second person" if personal else ""))
    if any(p.search(lower) for p in _COMPARISON_PATTERNS):
        categories.append(COMPARISON)
        signals.append("comparison wording")
    if any(p.search(lower) for p in _PROBLEM_PATTERNS):
        categories.append(PROBLEM_SOLUTION)
        signals.append("problem / desired-outcome wording")
    if compiled.search(text):
        categories.append(VERY_LONG)
        signals.append("matches the long-query pattern")
    return Classification(tuple(categories), n, tuple(signals))
