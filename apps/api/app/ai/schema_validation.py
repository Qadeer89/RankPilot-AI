"""Deterministic validation for AI-drafted JSON-LD structured data
(RankPilot AI Phase 3 "Schema Markup Automation").

The model is instructed never to invent business facts, but that
instruction alone is not trusted -- this module enforces it in code:
every property value in a proposed schema block must be traceable
verbatim to evidence RankPilot itself already crawled (title, meta
description, canonical URL, site name), and only a small, pre-approved
set of schema.org types and properties is ever accepted. There is no
path for a rating, review, price, author, or publisher to reach a
published page through this validator -- those keys are rejected
outright, not merely discouraged.
"""

from __future__ import annotations

import json

ALLOWED_SCHEMA_TYPES = {"WebPage", "Article"}

REQUIRED_PROPERTIES: dict[str, set[str]] = {
    "WebPage": {"name", "url"},
    "Article": {"headline", "url"},
}

# Every property this validator will ever accept, on any type. Adding a
# new one (author, publisher, aggregateRating, offers, ...) is a
# deliberate decision to review, not a side effect of a model wanting
# to use it -- RankPilot has no verified source of truth for any of
# those facts today.
ALLOWED_PROPERTY_KEYS = {"@context", "@type", "name", "headline", "url", "description", "inLanguage"}

ALLOWED_CONTEXT_VALUES = {"https://schema.org", "http://schema.org"}


def validate_schema_json(raw_json: str, evidence_values: list[str]) -> dict:
    """Parse and validate one JSON-LD object. Raises ValueError on any
    syntax problem, disallowed type/property, missing required
    property, or a value that isn't grounded in `evidence_values`
    (case-insensitive substring match against the evidence actually
    given to the model). Returns the parsed dict on success.
    """
    try:
        parsed = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Structured data is not valid JSON: {exc}") from exc

    if not isinstance(parsed, dict):
        raise ValueError("Structured data must be a single JSON object, not a list or scalar.")

    extra_keys = set(parsed.keys()) - ALLOWED_PROPERTY_KEYS
    if extra_keys:
        raise ValueError(f"Disallowed structured-data properties: {sorted(extra_keys)}")

    schema_type = parsed.get("@type")
    if schema_type not in ALLOWED_SCHEMA_TYPES:
        raise ValueError(f"@type must be one of {sorted(ALLOWED_SCHEMA_TYPES)}, got {schema_type!r}")

    if parsed.get("@context") not in ALLOWED_CONTEXT_VALUES:
        raise ValueError("@context must be https://schema.org")

    missing = REQUIRED_PROPERTIES[schema_type] - parsed.keys()
    if missing:
        raise ValueError(f"@type {schema_type} is missing required properties: {sorted(missing)}")

    haystack = " ".join(str(v) for v in evidence_values if v).lower()
    for key, value in parsed.items():
        if key in ("@context", "@type"):
            continue
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Property {key!r} must be a non-empty string.")
        if value.lower() not in haystack:
            raise ValueError(
                f"Property {key!r} value {value!r} is not grounded in the page evidence RankPilot "
                "crawled -- structured data may never state a fact it cannot verify."
            )

    return parsed
