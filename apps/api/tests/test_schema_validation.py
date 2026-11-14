import json

import pytest

from app.ai.schema_validation import validate_schema_json

EVIDENCE = ["About Us | Acme Co", "https://example.com/about", "Acme Co"]


def _schema(**overrides) -> str:
    base = {
        "@context": "https://schema.org",
        "@type": "WebPage",
        "name": "About Us | Acme Co",
        "url": "https://example.com/about",
    }
    base.update(overrides)
    return json.dumps(base)


def test_valid_webpage_schema_passes():
    parsed = validate_schema_json(_schema(), EVIDENCE)
    assert parsed["@type"] == "WebPage"


def test_valid_article_schema_passes():
    schema = json.dumps(
        {
            "@context": "https://schema.org",
            "@type": "Article",
            "headline": "About Us | Acme Co",
            "url": "https://example.com/about",
        }
    )
    parsed = validate_schema_json(schema, EVIDENCE)
    assert parsed["@type"] == "Article"


def test_rejects_malformed_json():
    with pytest.raises(ValueError, match="not valid JSON"):
        validate_schema_json("{not json", EVIDENCE)


def test_rejects_a_json_array_instead_of_an_object():
    with pytest.raises(ValueError, match="single JSON object"):
        validate_schema_json("[1, 2, 3]", EVIDENCE)


def test_rejects_disallowed_schema_type():
    with pytest.raises(ValueError, match="@type must be one of"):
        validate_schema_json(_schema(**{"@type": "Product"}), EVIDENCE)


def test_rejects_wrong_context():
    with pytest.raises(ValueError, match="@context must be"):
        validate_schema_json(_schema(**{"@context": "https://example.com/ns"}), EVIDENCE)


def test_rejects_missing_required_property():
    schema = json.dumps({"@context": "https://schema.org", "@type": "WebPage"})
    with pytest.raises(ValueError, match="missing required properties"):
        validate_schema_json(schema, EVIDENCE)


@pytest.mark.parametrize(
    "forbidden_key",
    ["author", "publisher", "aggregateRating", "review", "offers", "price", "ratingValue"],
)
def test_rejects_disallowed_properties_that_could_fabricate_facts(forbidden_key):
    with pytest.raises(ValueError, match="Disallowed structured-data properties"):
        validate_schema_json(_schema(**{forbidden_key: "something"}), EVIDENCE)


def test_rejects_a_value_not_grounded_in_the_evidence():
    """The core anti-hallucination guard: even a syntactically perfect,
    allowlisted-type, allowlisted-property schema is rejected if a
    value doesn't trace back to the evidence actually given to the
    model -- e.g. an invented description.
    """
    with pytest.raises(ValueError, match="not grounded in the page evidence"):
        validate_schema_json(_schema(description="Voted #1 best bakery in the city!"), EVIDENCE)


def test_accepts_a_value_that_is_a_substring_of_the_evidence_case_insensitively():
    parsed = validate_schema_json(_schema(name="acme co"), EVIDENCE)
    assert parsed["name"] == "acme co"


def test_rejects_a_non_string_property_value():
    with pytest.raises(ValueError, match="must be a non-empty string"):
        validate_schema_json(_schema(name=12345), EVIDENCE)
