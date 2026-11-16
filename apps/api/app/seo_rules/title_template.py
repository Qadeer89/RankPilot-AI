"""Site-wide title templates.

Many sites append their name to every page title in the page template
(`<title>{page title} | Brand</title>`). The CMS field RankPilot writes to
holds only the page's own part, but the crawled `<title>` already includes
the suffix. Without knowing that, a rewritten title that includes the brand
ends up with the brand twice ("X | Brand | Brand") and longer than before.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

# A separator surrounded by spaces, so hyphenated words and "Q&A" are not split.
_SEPARATOR = re.compile(r"\s+([|\-–—·:])\s+")
MIN_PAGES_FOR_DETECTION = 3
MIN_SHARE = 0.6
MIN_SEGMENT_LENGTH = 2


@dataclass(frozen=True)
class TitleSuffix:
    separator: str  # e.g. "|"
    text: str  # e.g. "Gul's Rehab Rawalpindi"

    @property
    def joined(self) -> str:
        return f" {self.separator} {self.text}"


def split_title(title: str) -> list[tuple[str, str]]:
    """[(separator-before, segment)], the first separator being ''."""
    parts: list[tuple[str, str]] = []
    position = 0
    separator = ""
    for match in _SEPARATOR.finditer(title):
        parts.append((separator, title[position:match.start()].strip()))
        separator = match.group(1)
        position = match.end()
    parts.append((separator, title[position:].strip()))
    return [(sep, seg) for sep, seg in parts if seg]


def detect_title_suffix(titles: list[str]) -> TitleSuffix | None:
    """The trailing segment most of the site's page titles end with, if there
    is one. Needs several pages so a single page's own wording is never
    mistaken for a template."""
    clean = [t for t in titles if t and t.strip()]
    if len(clean) < MIN_PAGES_FOR_DETECTION:
        return None
    last_segments: Counter[tuple[str, str]] = Counter()
    for title in clean:
        parts = split_title(title)
        if len(parts) >= 2 and len(parts[-1][1]) >= MIN_SEGMENT_LENGTH:
            last_segments[(parts[-1][0], parts[-1][1])] += 1
    if not last_segments:
        return None
    (separator, text), count = last_segments.most_common(1)[0]
    if count / len(clean) < MIN_SHARE:
        return None
    return TitleSuffix(separator=separator, text=text)


def _is_brand_like(segment: str, suffix: TitleSuffix) -> bool:
    a, b = segment.lower(), suffix.text.lower()
    return len(a) >= 3 and (a == b or a in b or b in a)


def strip_title_suffix(value: str, suffix: TitleSuffix | None) -> str:
    """Remove trailing brand segments the site's template adds anyway (the
    full suffix, or a shorter form of it such as "Brand" for "Brand City")."""
    if suffix is None:
        return value
    parts = split_title(value)
    while len(parts) >= 2 and _is_brand_like(parts[-1][1], suffix):
        parts.pop()
    if not parts:
        return value
    rebuilt = parts[0][1]
    for separator, segment in parts[1:]:
        rebuilt += f" {separator} {segment}"
    return rebuilt


_TEMPLATE_TAIL = re.compile(r"^\s+[|\-–—·:]\s+\S")


def title_matches(expected: str | None, found: str | None) -> bool:
    """Does the crawled title show the value that was applied? Either exactly,
    or with a template suffix appended after a separator."""
    expected, found = (expected or "").strip(), (found or "").strip()
    if not expected:
        return not found
    if found == expected:
        return True
    return found.startswith(expected) and bool(_TEMPLATE_TAIL.match(found[len(expected):]))


def has_duplicate_brand(title: str | None) -> bool:
    """"X | Brand | Brand", or the last two segments being the same name in
    a longer and a shorter form ("Brand" / "Brand City")."""
    parts = split_title(title or "")
    if len(parts) < 3:
        return False
    last, previous = parts[-1][1].lower(), parts[-2][1].lower()
    return len(previous) >= 3 and (last == previous or previous in last or last in previous)
