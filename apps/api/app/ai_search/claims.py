"""Finds verifiable-looking claims in a text and whether a source sits next to each.

The claim and citation patterns are adapted from `content_verify.py` in claude-seo
(https://github.com/AgriciDaniel/claude-seo), MIT License, Copyright (c) 2026 agricidaniel. They are English-only:
text in another language is not analysed, and the result says so instead of reporting "no claims"."""

from __future__ import annotations

import re

_CLAIM_PATTERNS: tuple[tuple[re.Pattern, str], ...] = (
    (re.compile(r"\b\d+(?:\.\d+)?\s*%\s+of\s+[a-zA-Z]+(?:\s+[a-zA-Z]+){0,4}", re.IGNORECASE), "statistic"),
    (re.compile(r"\b\d+(?:\.\d+)?\s*%"), "statistic"),
    (re.compile(r"\$\s?\d+(?:\.\d+)?\s*(?:million|billion|trillion|k|M|B)\b", re.IGNORECASE), "quantity"),
    (re.compile(r"\b\d{1,3}(?:,\d{3})+(?:\.\d+)?\s+\w+", re.IGNORECASE), "quantity"),
    (re.compile(r"\b\d+(?:\.\d+)?\s*(?:million|billion|trillion)\b", re.IGNORECASE), "quantity"),
    # "According" is matched in any case (a sentence-initial capital was missed upstream); the named source stays Capitalised.
    (re.compile(r"\b(?i:according\s+to\s+(?:a\s+)?)(?:[A-Z][a-z]+\s+){1,4}(?i:study|report|survey|analysis|paper)\b"), "authority"),
    (re.compile(r"\b(?:Forrester|Gartner|McKinsey|Pew|Nielsen|Statista|Deloitte|Edelman|MIT|Stanford|Harvard|Wharton|WHO|NHS|CDC)\s+(?:said|reports?|found|noted|recommends?)", re.IGNORECASE), "authority"),
    (re.compile(r"\b(?:studies|research|clinical trials|experts|doctors|scientists)\s+(?:show|shows|suggest|suggests|prove|proves|have found|agree)\b", re.IGNORECASE), "authority"),
    (re.compile(r"\bin\s+(?:19|20)\d{2}\b"), "temporal"),
    (re.compile(r"\bby\s+20\d{2}\b"), "temporal"),
    (re.compile(r"\b\d+(?:\.\d+)?\s*(?:x|times)\s+(?:more|less|faster|slower|higher|lower|better|worse)\b", re.IGNORECASE), "comparative"),
    (re.compile(r"\b(?:twice|thrice|half)\s+as\s+\w+", re.IGNORECASE), "comparative"),
)

_CITATION_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(r"\[[^\]]+\]\(https?://[^)]+\)"),
    re.compile(r"<a\s+[^>]*href=[\"']https?://[^\"']+[\"']"),
    re.compile(r"\[\^?\d+\]"),
    # "Per" needs a capital (it is also an ordinary word: "per week").
    re.compile(r"\b(?:(?:source\s*:|via\s*:|see\s+also\s*:|cited\s+(?:in|by)|according\s+to)\s+\S|per\s+(?-i:[A-Z]))", re.IGNORECASE),
)
_LATIN = re.compile(r"[A-Za-z]")
_ALPHA = re.compile(r"[^\W\d_]")


def english_coverage(text: str) -> float:
    """Share of letters that are Latin. Below ~0.6 the English patterns are not meaningful."""
    letters = _ALPHA.findall(text)
    return len(_LATIN.findall(text)) / len(letters) if letters else 1.0


def citation_near(text: str, position: int, window: int = 200) -> str | None:
    snippet = text[max(0, position - window): position + window]
    for pattern in _CITATION_PATTERNS:
        match = pattern.search(snippet)
        if match:
            return match.group(0)[:80]
    return None


def extract_claims(text: str) -> list[dict]:
    spans: list[tuple[int, int, str]] = []
    for pattern, kind in _CLAIM_PATTERNS:
        for m in pattern.finditer(text):
            if any(s <= m.start() < e or s < m.end() <= e for s, e, _ in spans):
                continue
            spans.append((m.start(), m.end(), kind))
    return [
        {"text": text[s:e].strip(), "kind": kind, "position": s, "citation": citation_near(text, s)}
        for s, e, kind in sorted(spans)
    ]


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def unsupported_claims(draft_text: str, page_text: str) -> list[dict]:
    """Claims in `draft_text` that the page does not already make and that carry no source of their own."""
    page = _norm(page_text)
    out = []
    for claim in extract_claims(draft_text):
        # An attribution IS the claim ("according to a Harvard study"), so a nearby "according to" cue cannot
        # vouch for it: it is judged by whether the page itself names that source.
        if claim["citation"] and claim["kind"] != "authority":
            continue
        needle = _norm(claim["text"])
        # a claim the page already states is the owner's own, already published, statement
        if needle and needle in page:
            continue
        if claim["kind"] == "authority":
            names = re.findall(r"\b[A-Z][A-Za-z]{2,}\b", claim["text"])
            if names and all(n.lower() in page for n in names):
                continue
        out.append(claim)
    return out
