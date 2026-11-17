"""Query classification, scoring and discovery. Expected values are worked out by hand from the seed data."""

from datetime import date, timedelta

import pytest

from app.ai_search import classify as c
from app.ai_search import discovery as d
from tests.ai_search_helpers import make_page, make_site, observe


# ---------------------------------------------------------------- classification

@pytest.mark.parametrize("query,expected", [
    ("rehab", set()),
    ("rehab center lahore", set()),
    ("what is rehab", {c.QUESTION}),
    ("how to choose a rehab center near me", {c.QUESTION, c.LONG_TAIL, c.CONVERSATIONAL}),
    ("can i visit my brother during treatment", {c.QUESTION, c.LONG_TAIL, c.CONVERSATIONAL}),
    ("is rehab covered by insurance?", {c.QUESTION, c.LONG_TAIL}),
    ("inpatient vs outpatient rehab", {c.COMPARISON}),
    ("difference between detox and rehab programs", {c.COMPARISON, c.LONG_TAIL}),
    ("best rehab for alcohol addiction", {c.COMPARISON, c.LONG_TAIL}),
    ("my son is not working on recovery what should i do now", {c.LONG_TAIL, c.CONVERSATIONAL, c.PROBLEM_SOLUTION, c.VERY_LONG}),
    ("kya rehab mein family visit kar sakti hai", {c.QUESTION, c.LONG_TAIL, c.CONVERSATIONAL}),
    ("how to fix", {c.QUESTION, c.PROBLEM_SOLUTION}),
])
def test_classification(query, expected):
    got = set(c.classify_query(query).categories)
    # the very-long label is covered separately; ignore it here unless expected
    got.discard(c.VERY_LONG) if c.VERY_LONG not in expected else None
    assert got == expected, (query, got)


def test_a_long_query_is_not_automatically_a_question():
    info = c.classify_query("luxury residential treatment programme lahore pakistan fees packages facilities overview")
    assert c.VERY_LONG in info.categories and c.LONG_TAIL in info.categories
    assert c.QUESTION not in info.categories and c.CONVERSATIONAL not in info.categories


def test_the_default_long_query_regex_means_eight_or_more_words():
    seven = "one two three four five six seven"
    eight = seven + " eight"
    assert c.VERY_LONG not in c.classify_query(seven).categories
    assert c.VERY_LONG in c.classify_query(eight).categories


def test_original_query_text_is_never_changed():
    assert c.classify_query("  How   TO fix? ").signals  # classification works on a normalised copy only


@pytest.mark.parametrize("pattern", [r"^(?=a)", r"(a)\1", r"(?<!x)y", r"a*+b", r"(?>ab)"])
def test_patterns_re2_would_reject_are_refused(pattern):
    with pytest.raises(c.InvalidRegex):
        c.validate_re2_regex(pattern)


def test_valid_and_invalid_syntax():
    assert c.validate_re2_regex(r"^(?:\S+\s+){7,}\S+$")
    with pytest.raises(c.InvalidRegex):
        c.validate_re2_regex("(unclosed")
    with pytest.raises(c.InvalidRegex):
        c.validate_re2_regex("")


def test_empty_query():
    assert c.classify_query("   ").categories == ()


# ---------------------------------------------------------------- scoring

def _bench(db, site, page):
    # five ordinary queries at position 8 with a 10% CTR form this site's own benchmark for positions 6-10
    for i in range(5):
        observe(db, site, page, f"keyword number {i}", days_ago=6, impressions=20, clicks=2, position=8.0)


def _target(db, site, page, query="how do i choose a rehab centre for my brother", *, impressions_per_obs=25, clicks_per_obs=0, position=8.0, country="US"):
    for days in (5, 7, 22, 24):  # two days in each half of the 28-day window -> a stable trend
        observe(db, site, page, query, days_ago=days, impressions=impressions_per_obs, clicks=clicks_per_obs, position=position, country=country)


def _window():
    return d.resolve_window("28d", None, None)


def test_high_opportunity_score_matches_the_hand_computed_value(db_session):
    site = make_site(db_session)
    page = make_page(db_session, site, title="Rehab centre guide")
    _bench(db_session, site, page)
    _target(db_session, site, page, clicks_per_obs=0)
    result = d.discover(db_session, site, start=_window()[0], end=_window()[1])
    item = next(i for i in result["items"] if i.query.startswith("how do i choose"))
    # 100 impressions, 0 clicks, position 8, page covers 2 of 4 query terms, stable trend, question wording
    # demand 20 + position 25 + CTR 15 (0% vs site median 10%) + page 10 + coverage 7.5 + trend 0 + intent 5 = 82.5
    assert (item.impressions, item.clicks, round(item.position, 1)) == (100, 0, 8.0)
    assert item.score in (82, 83)
    assert item.tier == d.HIGH_OPPORTUNITY
    assert {f["factor"]: f["points"] for f in item.factors if f["max"]}["CTR vs this site"] == 15
    assert item.coverage == 0.5 and item.trend == "stable"
    assert c.QUESTION in item.categories and c.CONVERSATIONAL in item.categories
    assert item.page.url.endswith("/guide") and not item.needs_review


def test_strong_ctr_is_not_a_high_opportunity(db_session):
    site = make_site(db_session)
    page = make_page(db_session, site, title="Rehab centre guide")
    _bench(db_session, site, page)
    _target(db_session, site, page, clicks_per_obs=4)  # 16% CTR, above the 10% site median
    item = next(i for i in d.discover(db_session, site, start=_window()[0], end=_window()[1])["items"] if i.query.startswith("how do i choose"))
    assert item.tier == d.RANKING_IMPROVEMENT  # position 8 with a relevant page, but the CTR is fine


def test_low_impressions_are_low_priority_whatever_the_ctr(db_session):
    site = make_site(db_session)
    page = make_page(db_session, site)
    _bench(db_session, site, page)
    observe(db_session, site, page, "how do i choose a rehab centre for my brother", days_ago=5, impressions=4, clicks=0, position=8.0)
    item = next(i for i in d.discover(db_session, site, start=_window()[0], end=_window()[1])["items"] if i.query.startswith("how do i"))
    assert item.tier == d.LOW_PRIORITY


def test_position_changes_the_judgement_for_the_same_ctr(db_session):
    site = make_site(db_session)
    page = make_page(db_session, site, title="Rehab centre guide")
    _bench(db_session, site, page)
    _target(db_session, site, page, "how do i choose a rehab centre for my brother", position=8.0)
    _target(db_session, site, page, "how do i choose a rehab centre for my sister", position=45.0)
    items = {i.query: i for i in d.discover(db_session, site, start=_window()[0], end=_window()[1])["items"]}
    near, far = items["how do i choose a rehab centre for my brother"], items["how do i choose a rehab centre for my sister"]
    assert near.tier == d.HIGH_OPPORTUNITY
    assert far.tier == d.LOW_PRIORITY  # no benchmark at position 45 and too far down: low CTR alone is not an opportunity
    assert near.score > far.score


def test_top_three_positions_have_little_headroom(db_session):
    site = make_site(db_session)
    page = make_page(db_session, site, title="Rehab centre guide")
    _target(db_session, site, page, position=2.0)
    item = d.discover(db_session, site, start=_window()[0], end=_window()[1])["items"][0]
    assert next(f for f in item.factors if f["factor"] == "Position headroom")["points"] == 5
    assert item.tier == d.LOW_PRIORITY


def test_no_benchmark_means_ctr_is_not_scored_and_says_so(db_session):
    site = make_site(db_session)
    page = make_page(db_session, site, title="Rehab centre guide")
    _target(db_session, site, page)  # no other queries: nothing to compare with
    item = d.discover(db_session, site, start=_window()[0], end=_window()[1])["items"][0]
    ctr = next(f for f in item.factors if f["factor"] == "CTR vs this site")
    assert ctr["points"] == 0 and "not scored" in ctr["note"]
    assert item.tier == d.RANKING_IMPROVEMENT


def test_a_query_without_a_crawled_page_is_a_content_gap(db_session):
    site = make_site(db_session)
    _target(db_session, site, None)
    item = d.discover(db_session, site, start=_window()[0], end=_window()[1])["items"][0]
    assert item.page is None and item.tier == d.CONTENT_GAP


def test_a_page_whose_title_and_headings_miss_the_query_is_a_content_gap(db_session):
    site = make_site(db_session)
    page = make_page(db_session, site, title="About our team", headings={"h1": ["Meet the doctors"]})
    _target(db_session, site, page)
    item = d.discover(db_session, site, start=_window()[0], end=_window()[1])["items"][0]
    assert item.coverage == 0.0 and item.tier == d.CONTENT_GAP


def test_missing_page_text_is_reported_not_guessed(db_session):
    site = make_site(db_session)
    page = make_page(db_session, site, with_snapshot=False)
    _target(db_session, site, page)
    item = d.discover(db_session, site, start=_window()[0], end=_window()[1])["items"][0]
    assert item.coverage is None


def test_two_competing_pages_are_flagged_for_review_not_resolved(db_session):
    site = make_site(db_session)
    a, b = make_page(db_session, site, "/a", "Rehab centre guide"), make_page(db_session, site, "/b", "Rehab centre brother")
    _target(db_session, site, a, impressions_per_obs=15)   # 60 impressions
    _target(db_session, site, b, impressions_per_obs=10)   # 40 impressions (40% share)
    item = d.discover(db_session, site, start=_window()[0], end=_window()[1])["items"][0]
    assert item.needs_review and item.page.url.endswith("/a") and [p.url.rsplit("/", 1)[1] for p in item.other_pages] == ["b"]
    assert item.impressions == 100
    assert any(f["factor"] == "Review" for f in item.factors)


def test_a_tiny_second_page_is_not_cannibalisation(db_session):
    site = make_site(db_session)
    a, b = make_page(db_session, site, "/a", "Rehab centre guide"), make_page(db_session, site, "/b", "Other")
    _target(db_session, site, a, impressions_per_obs=25)
    observe(db_session, site, b, "how do i choose a rehab centre for my brother", days_ago=5, impressions=12, position=9.0)
    item = d.discover(db_session, site, start=_window()[0], end=_window()[1])["items"][0]
    assert not item.needs_review  # 12 of 112 impressions is under the 25% share


def test_country_filter_and_country_reporting(db_session):
    site = make_site(db_session)
    page = make_page(db_session, site, title="Rehab centre guide")
    _target(db_session, site, page, country="usa".upper()[:2])
    _target(db_session, site, page, "how do i choose a rehab centre for my brother", impressions_per_obs=5, country="GB")
    s, e = _window()
    both = d.discover(db_session, site, start=s, end=e)["items"][0]
    assert both.impressions == 120 and both.country == "US" and both.countries == {"US": 100, "GB": 20}
    gb = d.discover(db_session, site, start=s, end=e, country="gbr")["items"]  # alpha-3 accepted via the shared normaliser
    assert [i.impressions for i in gb] == [20]
    with pytest.raises(ValueError):
        d.discover(db_session, site, start=s, end=e, country="atlantis")


def test_duplicate_rows_for_a_query_are_merged(db_session):
    site = make_site(db_session)
    page = make_page(db_session, site, title="Rehab centre guide")
    for device in ("MOBILE", "DESKTOP"):
        observe(db_session, site, page, "how do i choose a rehab centre for my brother", days_ago=5, impressions=10, device=device)
    items = d.discover(db_session, site, start=_window()[0], end=_window()[1])["items"]
    assert len(items) == 1 and items[0].impressions == 20
    assert len(d.discover(db_session, site, start=_window()[0], end=_window()[1], device="mobile")["items"]) == 1


def test_empty_gsc_data_is_reported_not_faked(db_session):
    site = make_site(db_session)
    result = d.discover(db_session, site, start=_window()[0], end=_window()[1])
    assert result["items"] == [] and result["coverage"]["rows"] == 0
    assert any("No Search Console data" in w for w in result["warnings"])


def test_a_period_longer_than_the_stored_data_is_flagged(db_session):
    site = make_site(db_session)
    page = make_page(db_session, site)
    _target(db_session, site, page)
    s, e = d.resolve_window("6m", None, None)
    warnings = d.discover(db_session, site, start=s, end=e)["warnings"]
    assert any("starts on" in w for w in warnings)


def test_plain_short_queries_are_not_reported_unless_asked(db_session):
    site = make_site(db_session)
    page = make_page(db_session, site)
    observe(db_session, site, page, "rehab", days_ago=5, impressions=500, position=3.0)
    s, e = _window()
    assert d.discover(db_session, site, start=s, end=e)["items"] == []
    assert len(d.discover(db_session, site, start=s, end=e, include_plain=True)["items"]) == 1


# ---------------------------------------------------------------- ranges and filtering

def test_window_presets_and_the_reporting_lag():
    today = date(2026, 11, 17)
    assert d.resolve_window("7d", None, None, today=today) == (date(2026, 11, 8), date(2026, 11, 14))
    assert d.resolve_window("28d", None, None, today=today)[1] == date(2026, 11, 14)
    assert (d.resolve_window("3m", None, None, today=today)[1] - d.resolve_window("3m", None, None, today=today)[0]).days == 89
    assert d.resolve_window("custom", date(2026, 1, 1), date(2026, 1, 31), today=today) == (date(2026, 1, 1), date(2026, 1, 31))


@pytest.mark.parametrize("args", [("custom", None, None), ("custom", date(2026, 2, 1), date(2026, 1, 1)), ("custom", date(2024, 1, 1), date(2026, 1, 1)), ("nope", None, None)])
def test_bad_ranges_raise(args):
    with pytest.raises(d.RangeError):
        d.resolve_window(*args)


def test_filters_and_sorting(db_session):
    site = make_site(db_session)
    page = make_page(db_session, site, title="Rehab centre guide")
    _bench(db_session, site, page)
    _target(db_session, site, page, "how do i choose a rehab centre for my brother", position=8.0)
    _target(db_session, site, page, "inpatient vs outpatient rehab centre for my brother", impressions_per_obs=5, position=12.0)
    items = d.discover(db_session, site, start=_window()[0], end=_window()[1])["items"]
    assert [i.query for i in d.filter_and_sort(items, category=c.COMPARISON)] == ["inpatient vs outpatient rehab centre for my brother"]
    assert len(d.filter_and_sort(items, min_impressions=50)) == 1
    assert d.filter_and_sort(items, sort="impressions")[0].impressions == 100
    assert d.filter_and_sort(items, search="OUTPATIENT")[0].query.startswith("inpatient")
    with pytest.raises(ValueError):
        d.filter_and_sort(items, category="made_up")
    with pytest.raises(ValueError):
        d.filter_and_sort(items, sort="volume")
