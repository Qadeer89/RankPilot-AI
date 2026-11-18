import pytest

from app.ai_search import agent as ag
from app.ai_search import claims, crawler_access as ca
from app.ai_search.page_content import parse_content

ORIGIN = "https://clinic.example"


# ---------------------------------------------------------------- claims

@pytest.mark.parametrize("text,kind", [
    ("Studies show that most patients improve.", "authority"),
    ("According to a Stanford study, results last.", "authority"),
    ("Gartner reports growth.", "authority"),
    ("Results are twice as durable.", "comparative"),
    ("Around 45% of patients return.", "statistic"),
    ("Founded in 2015 by doctors.", "temporal"),
])
def test_claim_kinds_are_found(text, kind):
    assert kind in {c["kind"] for c in claims.extract_claims(text)}


def test_a_nearby_source_marks_a_claim_as_cited():
    cited = claims.extract_claims("Around 45% of patients return, according to NHS data [1].")
    assert cited and all(c["citation"] for c in cited)
    bare = claims.extract_claims("Around 45% of patients return.")
    assert bare and bare[0]["citation"] is None


def test_a_claim_the_page_already_makes_is_not_flagged():
    page = "Our clinic reports that 45% of patients return within a year."
    assert claims.unsupported_claims("45% of patients return", page) == []
    assert claims.unsupported_claims("Experts agree this is best", page)[0]["kind"] == "authority"


def test_non_english_text_is_recognised_as_outside_the_patterns():
    assert claims.english_coverage("هذا نص عربي عن العلاج الطبيعي") < 0.3
    assert claims.english_coverage("Physiotherapy helps recovery") > 0.9
    assert claims.english_coverage("") == 1.0


# ---------------------------------------------------------------- draft quality uses the claim checker

PAGE = ("<html><head><title>Rehab</title></head><body><main><h1>Rehab</h1><p>We offer residential treatment with medical supervision and "
        "family sessions. Stays are usually between 28 and 90 days.</p><a href='/a'>a</a><a href='/b'>b</a><a href='/c'>c</a></main></body></html>")


def _draft(answer, **over):
    base = dict(search_intent="informational", user_question="q", page_matches_intent=True, intent_note="", current_answer_assessment="a",
                missing_information=[], needs_owner_input=[], direct_answer=answer, suggested_heading="How long does rehab take?", faq_recommended=False,
                faq_suggestions=[], supporting_examples=[], internal_links=[], schema_review_note="", rationale="r", confidence=0.5)
    base.update(over)
    return ag.AiSearchDraft(**base)


def _qc(answer):
    c = parse_content(PAGE, url=f"{ORIGIN}/rehab", hostname="clinic.example")
    return ag.quality_checks(_draft(answer), query="how long does rehab take", content=c, allowed_links=c.internal_links)


def _status(result, name):
    return next((x["status"] for x in result["checks"] if x["check"] == name), None)


def test_an_invented_authority_blocks_the_draft():
    r = _qc("According to a Harvard study, most programmes run between 28 and 90 days, and the plan is reviewed weekly with the family.")
    assert r["blocked"] and _status(r, "Attributions are on the page") == "fail"


def test_an_unsupported_comparison_is_a_warning():
    r = _qc("Stays run between 28 and 90 days, and families find our reviews twice as thorough as elsewhere, with weekly plan reviews.")
    assert _status(r, "Comparisons are supported") == "warn" and not r["blocked"]


def test_a_plain_answer_passes_the_attribution_check():
    assert _status(_qc("Stays are usually between 28 and 90 days, with medical supervision and family sessions during the programme."), "Attributions are on the page") == "pass"


def test_non_english_drafts_say_the_claim_check_did_not_run():
    r = _qc("عادة تستمر الإقامة بين 28 و 90 يوما مع إشراف طبي وجلسات للعائلة طوال فترة البرنامج العلاجي.")
    assert _status(r, "Attributions are on the page") == "warn"


# ---------------------------------------------------------------- AI crawler access

ROBOTS = """User-agent: *
Disallow: /private/

User-agent: GPTBot
Disallow: /

User-agent: Claude-SearchBot
Allow: /
Disallow: /members/
"""


def _states(text, sample=None):
    return {r["token"]: r["state"] for r in ca.evaluate(text, ORIGIN, sample)}


def test_a_named_group_replaces_the_wildcard_group():
    s = _states(ROBOTS)
    assert s["GPTBot"] == "blocked" and s["OAI-SearchBot"] == "allowed" and s["Googlebot"] == "allowed" and s["Claude-SearchBot"] == "allowed"


def test_a_page_in_a_disallowed_folder_is_reported_per_page():
    s = _states(ROBOTS, f"{ORIGIN}/private/guide")
    assert s["OAI-SearchBot"] == "partly_blocked"  # the site root is open, this page is not
    assert _states(ROBOTS, f"{ORIGIN}/members/x")["Claude-SearchBot"] == "partly_blocked"


def test_no_rules_means_everything_is_allowed_and_unreadable_means_unknown():
    assert set(_states("").values()) == {"allowed"}
    assert set(_states(None).values()) == {"unknown"}


def test_summary_separates_search_blocks_from_training_blocks_and_never_calls_blocking_an_error():
    blocked_all = "User-agent: *\nDisallow: /\n"
    summary = ca.summarise(ca.evaluate(blocked_all, ORIGIN))
    assert "OAI-SearchBot" in summary["search_crawlers_blocked"] and "GPTBot" in summary["training_crawlers_blocked"]
    only_training = ca.summarise(ca.evaluate("User-agent: GPTBot\nDisallow: /\n", ORIGIN))
    assert only_training["search_crawlers_blocked"] == [] and only_training["training_crawlers_blocked"] == ["GPTBot"]
    assert ca.summarise(ca.evaluate(None, ORIGIN))["unknown"] is True


@pytest.mark.parametrize("status,expected_text,expected_problem", [(404, "", None), (200, "User-agent: *\nAllow: /\n", None), (503, None, "HTTP 503"), (429, None, "HTTP 429")])
def test_robots_fetch_follows_rfc_9309_for_error_statuses(monkeypatch, status, expected_text, expected_problem):
    from app.crawler.fetch import FetchResult
    monkeypatch.setattr(ca, "safe_fetch", lambda url, **kw: FetchResult(final_url=url, status_code=status, headers={}, body="User-agent: *\nAllow: /\n", redirect_chain=[]))
    text, problem = ca.fetch_robots_text(ORIGIN)
    assert text == expected_text and (problem is None if expected_problem is None else expected_problem in problem)


def test_a_network_failure_is_unknown_not_allowed(monkeypatch):
    from app.crawler.fetch import FetchError
    def boom(url, **kw):
        raise FetchError("timeout")
    monkeypatch.setattr(ca, "safe_fetch", boom)
    result = ca.check(ORIGIN)
    assert result["summary"]["unknown"] is True and result["problem"] == "timeout" and "robots.txt only" in result["note"]
