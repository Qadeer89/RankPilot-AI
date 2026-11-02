"""Golden positive/negative/boundary fixtures for every implemented SEO
rule (RP13-023). Each rule-check function is called directly against a
hand-built PageSnapshot (never persisted -- these functions only read
attributes, never query the DB), so this is fast, deterministic, and
independent of the full crawl pipeline that tests/test_seo_rules_engine.py
exercises.

Per rule: at least one case that must trigger it, one that must not, and
-- where the rule has a numeric threshold -- the exact boundary value on
each side. This is the "every implemented rule has positive/negative/
boundary unit fixtures" release gate, not a claim about real-world
precision (RANKPILOT_AI_V1.3_IMPLEMENTATION_REQUIREMENTS.md #11.2).
"""

import uuid
from datetime import datetime, timezone

from app.models.page import Page
from app.models.page_snapshot import PageSnapshot
from app.seo_rules.rules import duplicates, http_status, indexability, links, metadata, sitemap, structured_data


def _snapshot(**overrides) -> PageSnapshot:
    defaults = dict(
        page_id=uuid.uuid4(),
        crawl_job_id=uuid.uuid4(),
        fetched_at=datetime.now(timezone.utc),
        status_code=200,
        redirect_count=0,
        title="A Perfectly Reasonable Page Title",  # 34 chars: inside [15, 60]
        meta_description="A reasonably sized meta description that fits comfortably within the limit.",  # 78 chars
        canonical_url=None,
        robots_directives=[],
        headings_json={"h1": ["One heading"]},
        schema_json=[],
        internal_links_json=[],
        content_fingerprint=None,
    )
    defaults.update(overrides)
    return PageSnapshot(**defaults)


def _rule_codes(candidates) -> set[str]:
    return {c.rule_code for c in candidates}


def _page(normalized_url: str, last_status_code: int | None = 200) -> Page:
    now = datetime.now(timezone.utc)
    return Page(
        id=uuid.uuid4(),
        website_id=uuid.uuid4(),
        canonical_url=normalized_url,
        normalized_url=normalized_url,
        first_seen_at=now,
        last_seen_at=now,
        last_status_code=last_status_code,
    )


# --- http_status.py ---------------------------------------------------


def test_http_error_status_negative_on_200():
    assert "HTTP_ERROR_STATUS" not in _rule_codes(http_status.check(uuid.uuid4(), _snapshot(status_code=200)))


def test_http_error_status_boundary_399_is_healthy():
    assert "HTTP_ERROR_STATUS" not in _rule_codes(http_status.check(uuid.uuid4(), _snapshot(status_code=399)))


def test_http_error_status_boundary_400_triggers_warning():
    candidates = http_status.check(uuid.uuid4(), _snapshot(status_code=400))
    found = next(c for c in candidates if c.rule_code == "HTTP_ERROR_STATUS")
    assert found.severity.value == "warning"


def test_http_error_status_boundary_499_is_warning_not_critical():
    candidates = http_status.check(uuid.uuid4(), _snapshot(status_code=499))
    found = next(c for c in candidates if c.rule_code == "HTTP_ERROR_STATUS")
    assert found.severity.value == "warning"


def test_http_error_status_boundary_500_is_critical():
    candidates = http_status.check(uuid.uuid4(), _snapshot(status_code=500))
    found = next(c for c in candidates if c.rule_code == "HTTP_ERROR_STATUS")
    assert found.severity.value == "critical"


def test_http_error_status_positive_on_missing_status_code():
    assert "HTTP_ERROR_STATUS" in _rule_codes(http_status.check(uuid.uuid4(), _snapshot(status_code=None)))


def test_redirect_chain_negative_on_zero_redirects():
    assert "REDIRECT_CHAIN" not in _rule_codes(http_status.check(uuid.uuid4(), _snapshot(redirect_count=0)))


def test_redirect_chain_boundary_one_hop_is_healthy():
    assert "REDIRECT_CHAIN" not in _rule_codes(http_status.check(uuid.uuid4(), _snapshot(redirect_count=1)))


def test_redirect_chain_boundary_two_hops_triggers():
    assert "REDIRECT_CHAIN" in _rule_codes(http_status.check(uuid.uuid4(), _snapshot(redirect_count=2)))


# --- indexability.py ---------------------------------------------------


def test_noindex_directive_positive():
    assert "NOINDEX_DIRECTIVE" in _rule_codes(
        indexability.check(uuid.uuid4(), "https://example.com/", _snapshot(robots_directives=["noindex"]))
    )


def test_noindex_directive_negative():
    assert "NOINDEX_DIRECTIVE" not in _rule_codes(
        indexability.check(uuid.uuid4(), "https://example.com/", _snapshot(robots_directives=[]))
    )


def test_canonical_missing_positive():
    assert "CANONICAL_MISSING" in _rule_codes(
        indexability.check(uuid.uuid4(), "https://example.com/", _snapshot(canonical_url=None))
    )


def test_canonical_missing_negative_when_canonical_matches():
    candidates = indexability.check(
        uuid.uuid4(), "https://example.com/page", _snapshot(canonical_url="https://example.com/page")
    )
    assert "CANONICAL_MISSING" not in _rule_codes(candidates)
    assert "CANONICAL_MISMATCH" not in _rule_codes(candidates)


def test_canonical_mismatch_positive_on_different_page():
    assert "CANONICAL_MISMATCH" in _rule_codes(
        indexability.check(
            uuid.uuid4(), "https://example.com/page-a", _snapshot(canonical_url="https://example.com/page-b")
        )
    )


def test_canonical_mismatch_boundary_case_and_scheme_normalization_is_not_a_mismatch():
    # normalize_frontier_url lowercases scheme/host, so differing only by
    # case must not be flagged as a mismatch.
    candidates = indexability.check(
        uuid.uuid4(), "https://Example.com/page", _snapshot(canonical_url="HTTPS://example.com/page")
    )
    assert "CANONICAL_MISMATCH" not in _rule_codes(candidates)


# --- metadata.py ---------------------------------------------------


def test_title_missing_positive_on_none():
    assert "TITLE_MISSING" in _rule_codes(metadata.check(uuid.uuid4(), _snapshot(title=None)))


def test_title_missing_positive_on_empty_string():
    assert "TITLE_MISSING" in _rule_codes(metadata.check(uuid.uuid4(), _snapshot(title="")))


def test_title_too_long_boundary_60_chars_is_healthy():
    assert "TITLE_TOO_LONG" not in _rule_codes(metadata.check(uuid.uuid4(), _snapshot(title="x" * 60)))


def test_title_too_long_boundary_61_chars_triggers():
    assert "TITLE_TOO_LONG" in _rule_codes(metadata.check(uuid.uuid4(), _snapshot(title="x" * 61)))


def test_title_too_short_boundary_15_chars_is_healthy():
    assert "TITLE_TOO_SHORT" not in _rule_codes(metadata.check(uuid.uuid4(), _snapshot(title="x" * 15)))


def test_title_too_short_boundary_14_chars_triggers():
    assert "TITLE_TOO_SHORT" in _rule_codes(metadata.check(uuid.uuid4(), _snapshot(title="x" * 14)))


def test_meta_description_missing_positive():
    assert "META_DESCRIPTION_MISSING" in _rule_codes(metadata.check(uuid.uuid4(), _snapshot(meta_description=None)))


def test_meta_description_missing_negative():
    assert "META_DESCRIPTION_MISSING" not in _rule_codes(
        metadata.check(uuid.uuid4(), _snapshot(meta_description="Present."))
    )


def test_meta_description_too_long_boundary_160_chars_is_healthy():
    assert "META_DESCRIPTION_TOO_LONG" not in _rule_codes(
        metadata.check(uuid.uuid4(), _snapshot(meta_description="x" * 160))
    )


def test_meta_description_too_long_boundary_161_chars_triggers():
    assert "META_DESCRIPTION_TOO_LONG" in _rule_codes(
        metadata.check(uuid.uuid4(), _snapshot(meta_description="x" * 161))
    )


def test_heading_h1_missing_positive():
    assert "HEADING_H1_MISSING" in _rule_codes(metadata.check(uuid.uuid4(), _snapshot(headings_json={"h1": []})))


def test_heading_h1_missing_negative_on_exactly_one():
    candidates = metadata.check(uuid.uuid4(), _snapshot(headings_json={"h1": ["Only heading"]}))
    assert "HEADING_H1_MISSING" not in _rule_codes(candidates)
    assert "HEADING_MULTIPLE_H1" not in _rule_codes(candidates)


def test_heading_multiple_h1_boundary_two_triggers():
    assert "HEADING_MULTIPLE_H1" in _rule_codes(
        metadata.check(uuid.uuid4(), _snapshot(headings_json={"h1": ["First", "Second"]}))
    )


# --- structured_data.py ---------------------------------------------------


def test_structured_data_parse_error_positive():
    assert "STRUCTURED_DATA_PARSE_ERROR" in _rule_codes(
        structured_data.check(uuid.uuid4(), _snapshot(schema_json=[{"raw": "{bad json}", "parse_error": "Expecting value"}]))
    )


def test_structured_data_parse_error_negative_on_valid_block():
    assert "STRUCTURED_DATA_PARSE_ERROR" not in _rule_codes(
        structured_data.check(uuid.uuid4(), _snapshot(schema_json=[{"raw": "{}", "parsed": {}, "parse_error": None}]))
    )


def test_structured_data_parse_error_negative_on_no_blocks():
    assert structured_data.check(uuid.uuid4(), _snapshot(schema_json=[])) == []


# --- duplicates.py ---------------------------------------------------


def test_duplicate_title_positive_on_two_matching_pages():
    page_a, page_b = uuid.uuid4(), uuid.uuid4()
    snapshots = {
        page_a: _snapshot(title="Same Title Everywhere", meta_description="Description A"),
        page_b: _snapshot(title="Same Title Everywhere", meta_description="Description B"),
    }
    candidates = duplicates.check_site(snapshots)
    codes_by_page = {c.page_id: c.rule_code for c in candidates}
    assert codes_by_page[page_a] == "DUPLICATE_TITLE"
    assert codes_by_page[page_b] == "DUPLICATE_TITLE"


def test_duplicate_title_negative_on_unique_titles():
    page_a, page_b = uuid.uuid4(), uuid.uuid4()
    snapshots = {
        page_a: _snapshot(title="Title One", meta_description="Description A"),
        page_b: _snapshot(title="Title Two", meta_description="Description B"),
    }
    assert duplicates.check_site(snapshots) == []


def test_duplicate_title_negative_when_both_missing():
    """Two pages that both lack a title are not duplicates of each
    other -- the falsy check intentionally excludes empty values.
    """
    page_a, page_b = uuid.uuid4(), uuid.uuid4()
    snapshots = {
        page_a: _snapshot(title=None, meta_description="Description A"),
        page_b: _snapshot(title=None, meta_description="Description B"),
    }
    assert duplicates.check_site(snapshots) == []


def test_duplicate_meta_description_positive():
    page_a, page_b = uuid.uuid4(), uuid.uuid4()
    snapshots = {
        page_a: _snapshot(title="Title A", meta_description="Shared description text."),
        page_b: _snapshot(title="Title B", meta_description="Shared description text."),
    }
    assert {c.rule_code for c in duplicates.check_site(snapshots)} == {"DUPLICATE_META_DESCRIPTION"}


# --- links.py ---------------------------------------------------


def test_broken_internal_link_positive():
    source_id = uuid.uuid4()
    target_page = _page("https://example.com/broken", last_status_code=404)
    pages_by_url = {"https://example.com/broken": target_page}
    snapshots = {source_id: _snapshot(internal_links_json=["https://example.com/broken"])}

    candidates = links.check_broken_links(pages_by_url, snapshots)
    assert _rule_codes(candidates) == {"BROKEN_INTERNAL_LINK"}
    assert candidates[0].page_id == source_id


def test_broken_internal_link_negative_when_target_is_healthy():
    source_id = uuid.uuid4()
    target_page = _page("https://example.com/fine", last_status_code=200)
    pages_by_url = {"https://example.com/fine": target_page}
    snapshots = {source_id: _snapshot(internal_links_json=["https://example.com/fine"])}

    assert links.check_broken_links(pages_by_url, snapshots) == []


def test_broken_internal_link_negative_when_target_unknown():
    """An un-crawled/unknown link target is not classified as broken --
    a documented limitation (RANKPILOT_AI_V1.3... #4.1), not a bug.
    """
    source_id = uuid.uuid4()
    snapshots = {source_id: _snapshot(internal_links_json=["https://example.com/never-crawled"])}

    assert links.check_broken_links({}, snapshots) == []


def test_orphan_page_candidate_positive():
    page = _page("https://example.com/orphan")
    candidates = links.check_orphan_pages(
        sitemap_normalized_urls={"https://example.com/orphan"},
        pages_by_normalized_url={"https://example.com/orphan": page},
        snapshots_by_page_id={},
    )
    assert _rule_codes(candidates) == {"ORPHAN_PAGE_CANDIDATE"}
    assert candidates[0].page_id == page.id


def test_orphan_page_candidate_negative_when_linked_from_a_crawled_page():
    page = _page("https://example.com/not-orphan")
    linking_snapshot = _snapshot(internal_links_json=["https://example.com/not-orphan"])
    candidates = links.check_orphan_pages(
        sitemap_normalized_urls={"https://example.com/not-orphan"},
        pages_by_normalized_url={"https://example.com/not-orphan": page},
        snapshots_by_page_id={uuid.uuid4(): linking_snapshot},
    )
    assert candidates == []


def test_orphan_page_candidate_negative_when_page_was_never_fetched():
    candidates = links.check_orphan_pages(
        sitemap_normalized_urls={"https://example.com/never-fetched"},
        pages_by_normalized_url={},
        snapshots_by_page_id={},
    )
    assert candidates == []


# --- sitemap.py ---------------------------------------------------


def test_sitemap_url_error_positive():
    page = _page("https://example.com/gone", last_status_code=404)
    candidates = sitemap.check_sitemap_urls(
        sitemap_normalized_urls={"https://example.com/gone"},
        pages_by_normalized_url={"https://example.com/gone": page},
    )
    assert _rule_codes(candidates) == {"SITEMAP_URL_ERROR"}


def test_sitemap_url_error_boundary_399_is_healthy():
    page = _page("https://example.com/ok", last_status_code=399)
    candidates = sitemap.check_sitemap_urls(
        sitemap_normalized_urls={"https://example.com/ok"},
        pages_by_normalized_url={"https://example.com/ok": page},
    )
    assert candidates == []


def test_sitemap_url_error_boundary_400_triggers():
    page = _page("https://example.com/edge", last_status_code=400)
    candidates = sitemap.check_sitemap_urls(
        sitemap_normalized_urls={"https://example.com/edge"},
        pages_by_normalized_url={"https://example.com/edge": page},
    )
    assert _rule_codes(candidates) == {"SITEMAP_URL_ERROR"}


def test_sitemap_url_error_negative_when_page_not_yet_crawled():
    candidates = sitemap.check_sitemap_urls(
        sitemap_normalized_urls={"https://example.com/unseen"}, pages_by_normalized_url={}
    )
    assert candidates == []
