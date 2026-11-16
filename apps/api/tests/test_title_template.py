"""A site's title template (`{page} | Brand`) and the double-brand bug it caused
when RankPilot wrote a full title, brand included, into a CMS title field."""

import json
import uuid
from datetime import datetime, timezone

import pytest

from app.ai import content_agent, runner
from app.models.crawl_job import CrawlJob, CrawlStatus, CrawlTrigger
from app.models.organization import Organization
from app.models.page import Page
from app.models.page_snapshot import PageSnapshot
from app.models.seo_opportunity import SEOOpportunity
from app.models.website import Website
from app.seo_rules.site_title import site_title_suffix
from app.seo_rules.title_template import (
    TitleSuffix,
    detect_title_suffix,
    has_duplicate_brand,
    split_title,
    strip_title_suffix,
    title_matches,
)
from tests.test_ai_content_agent import _FakeClient, _fake_openai_response, _valid_payload

GUL = TitleSuffix("|", "Gul's Rehab Rawalpindi")


def test_split_title_only_splits_on_spaced_separators():
    assert [s for _, s in split_title("Q&A: Knee-pain help | Gul's Rehab")] == ["Q&A: Knee-pain help", "Gul's Rehab"]
    assert [s for _, s in split_title("Post-Acne Marks vs Scars")] == ["Post-Acne Marks vs Scars"]


def test_suffix_is_detected_only_when_most_pages_share_it():
    shared = ["A | Brand", "B | Brand", "C | Brand", "D | Other"]
    assert detect_title_suffix(shared) == TitleSuffix("|", "Brand")
    assert detect_title_suffix(["A | X", "B | Y", "C | Z", "D | W"]) is None  # no common tail
    assert detect_title_suffix(["A | Brand", "B | Brand"]) is None  # too few pages to call it a template
    assert detect_title_suffix(["One", "Two", "Three"]) is None  # no separators at all


def test_a_template_is_still_found_when_earlier_fixes_already_doubled_it():
    titles = ["A | Brand | Brand", "B | Brand", "C | Brand | Brand", "D | Brand"]
    assert detect_title_suffix(titles).text == "Brand"


@pytest.mark.parametrize(
    "value,expected",
    [
        ("Frozen Shoulder Recovery | Gul's Rehab Rawalpindi", "Frozen Shoulder Recovery"),
        ("Post-Acne Marks vs Scars: Key Differences | Gul's Rehab", "Post-Acne Marks vs Scars: Key Differences"),  # shorter brand form
        ("Frozen Shoulder Recovery | Gul's Rehab | Gul's Rehab Rawalpindi", "Frozen Shoulder Recovery"),
        ("Knee Pain on Stairs", "Knee Pain on Stairs"),  # nothing to strip
        ("Rehab Tips | Daily Exercises", "Rehab Tips | Daily Exercises"),  # a real second part is kept
    ],
)
def test_strip_removes_only_the_brand_the_template_adds(value, expected):
    assert strip_title_suffix(value, GUL) == expected


def test_strip_without_a_known_template_changes_nothing():
    assert strip_title_suffix("Anything | Brand", None) == "Anything | Brand"


def test_title_matches_accepts_exact_and_template_suffix_but_not_other_text():
    assert title_matches("Frozen Shoulder", "Frozen Shoulder")
    assert title_matches("Frozen Shoulder", "Frozen Shoulder | Gul's Rehab Rawalpindi")
    assert not title_matches("Frozen Shoulder", "Frozen Shoulder Recovery")  # different words, not a suffix
    assert not title_matches("Frozen Shoulder", "Old Title | Brand")
    assert not title_matches("X", None)


@pytest.mark.parametrize(
    "title,expected",
    [
        ("QA Services | LeadFlow Studio | LeadFlow Studio", True),
        ("Recovery | Gul's Rehab | Gul's Rehab Rawalpindi", True),
        ("Recovery | Gul's Rehab Rawalpindi", False),
        ("Plain title", False),
        (None, False),
    ],
)
def test_duplicate_brand_detection(title, expected):
    assert has_duplicate_brand(title) is expected


def _site_with_template(db_session):
    org = Organization(name="Template Org", slug=f"tpl-{uuid.uuid4().hex[:8]}")
    db_session.add(org)
    db_session.flush()
    site = Website(organization_id=org.id, canonical_url="https://clinic.example/", hostname="clinic.example",
                   display_name="Clinic")
    db_session.add(site)
    db_session.flush()
    job = CrawlJob(website_id=site.id, trigger=CrawlTrigger.manual, status=CrawlStatus.completed)
    db_session.add(job)
    db_session.flush()
    now = datetime.now(timezone.utc)
    snapshots = []
    for slug, title in [("a", "Knee Pain | Clinic Rawalpindi"), ("b", "Hip Hinge | Clinic Rawalpindi"),
                        ("c", "Back Pain | Clinic Rawalpindi"), ("d", "Frozen Shoulder Recovery Guide | Clinic Rawalpindi")]:
        page = Page(website_id=site.id, canonical_url=f"https://clinic.example/{slug}",
                    normalized_url=f"https://clinic.example/{slug}", first_seen_at=now, last_seen_at=now)
        db_session.add(page)
        db_session.flush()
        snap = PageSnapshot(page_id=page.id, crawl_job_id=job.id, fetched_at=now, status_code=200, title=title,
                            canonical_url=page.canonical_url, headings_json={})
        db_session.add(snap)
        snapshots.append((page, snap))
    opp = SEOOpportunity(website_id=site.id, page_id=snapshots[3][0].id, category="metadata",
                         title="Shorten an overlong page title", rationale="Too long.", impact_estimate=0.3,
                         confidence=0.6, effort_estimate=0.2, risk_tier=1)
    db_session.add(opp)
    db_session.flush()
    return site, opp, snapshots[3][1]


def test_the_site_title_template_is_learned_from_its_crawled_titles(db_session):
    site, _, _ = _site_with_template(db_session)
    assert site_title_suffix(db_session, site) == TitleSuffix("|", "Clinic Rawalpindi")


def test_the_model_is_told_about_the_template_and_sees_the_title_without_it(db_session, monkeypatch):
    site, opp, snap = _site_with_template(db_session)
    seen = {}

    class Capture:
        def __init__(self, response):
            def create(**kwargs):
                seen.update(kwargs)
                return response
            self.chat = type("C", (), {"completions": type("X", (), {"create": staticmethod(create)})})()

    payload = _valid_payload(opp.id)
    payload["proposed_actions"][0]["target_url"] = "https://clinic.example/d"
    monkeypatch.setattr(runner, "get_openai_client", lambda: Capture(_fake_openai_response(payload)))

    content_agent.propose_content_fix(db_session, site, opp, snap)

    system = seen["messages"][0]["content"]
    user = seen["messages"][1]["content"]
    assert "TITLE TEMPLATE" in system
    evidence = json.loads(user.split("PAGE EVIDENCE (untrusted, see system instructions):\n")[1])
    assert evidence["site_title_suffix"] == " | Clinic Rawalpindi"
    assert evidence["current_title"] == "Frozen Shoulder Recovery Guide"


def test_a_title_written_with_the_brand_is_stored_without_it(db_session, monkeypatch):
    """The live bug: the model adds the brand, the site template adds it again."""
    site, opp, snap = _site_with_template(db_session)
    payload = _valid_payload(opp.id)
    payload["proposed_actions"][0].update(
        target_url="https://clinic.example/d", value="Frozen Shoulder Recovery: Stages | Clinic Rawalpindi"
    )
    monkeypatch.setattr(runner, "get_openai_client", lambda: _FakeClient(_fake_openai_response(payload)))

    proposal = content_agent.propose_content_fix(db_session, site, opp, snap)

    assert proposal.proposed_actions[0].value == "Frozen Shoulder Recovery: Stages"


def test_a_site_without_a_template_is_untouched(db_session, monkeypatch):
    from tests.test_ai_content_agent import _make_website_and_opportunity

    website, opportunity, snapshot = _make_website_and_opportunity(db_session)
    payload = _valid_payload(opportunity.id)  # value "Example — Home"
    monkeypatch.setattr(runner, "get_openai_client", lambda: _FakeClient(_fake_openai_response(payload)))

    proposal = content_agent.propose_content_fix(db_session, website, opportunity, snapshot)

    assert proposal.proposed_actions[0].value == "Example — Home"
    assert "TITLE TEMPLATE" not in content_agent.SYSTEM_PROMPT
