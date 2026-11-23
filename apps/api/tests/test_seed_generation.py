import uuid
from datetime import datetime, timezone

from app.keywords.seed_generation import _topic_words, generate_seed_keywords
from app.models.crawl_job import CrawlJob, CrawlStatus, CrawlTrigger
from app.models.organization import Organization
from app.models.page import Page
from app.models.page_snapshot import PageSnapshot
from app.models.website import Website


def test_topic_words_match_plurals_and_ignore_stopwords():
    assert "stair" in _topic_words("Knee Pain on Stairs")
    assert "the" not in _topic_words("the knee")


def test_generic_h2_headings_are_not_seeds(db_session):
    org = Organization(name="Seed Org", slug=f"seed-{uuid.uuid4().hex[:8]}")
    db_session.add(org)
    db_session.flush()
    site = Website(organization_id=org.id, canonical_url="https://e.com/", hostname="e.com", display_name="Rehab Clinic")
    db_session.add(site)
    db_session.flush()
    now = datetime.now(timezone.utc)
    page = Page(website_id=site.id, canonical_url="https://e.com/knee", normalized_url="https://e.com/knee",
                first_seen_at=now, last_seen_at=now)
    db_session.add(page)
    db_session.flush()
    job = CrawlJob(website_id=site.id, trigger=CrawlTrigger.manual, status=CrawlStatus.pending)
    db_session.add(job)
    db_session.flush()
    snap_kwargs = {"crawl_job_id": job.id}
    db_session.add(
        PageSnapshot(
            page_id=page.id, fetched_at=now, title="Knee Pain on Stairs: Causes", headings_json={
                "h1": ["Knee Pain on the Stairs"],
                "h2": ["In this article", "What usually helps", "Pain at the front of the knee", "Exercises to build stair strength"],
            }, **snap_kwargs,
        )
    )
    db_session.flush()

    seeds = [s.lower() for s in generate_seed_keywords(db_session, site)]

    assert "pain at the front of the knee" in seeds
    assert "exercises to build stair strength" in seeds
    assert "in this article" not in seeds
    assert "what usually helps" not in seeds


def _site_with_page(db_session, headings, title="Knee Pain on Stairs: Causes"):
    org = Organization(name="Seed Org", slug=f"seed-{uuid.uuid4().hex[:8]}")
    db_session.add(org)
    db_session.flush()
    site = Website(organization_id=org.id, canonical_url="https://e.com/", hostname="e.com", display_name="Rehab Clinic")
    db_session.add(site)
    db_session.flush()
    now = datetime.now(timezone.utc)
    page = Page(website_id=site.id, canonical_url="https://e.com/knee", normalized_url="https://e.com/knee", first_seen_at=now, last_seen_at=now)
    db_session.add(page)
    db_session.flush()
    job = CrawlJob(website_id=site.id, trigger=CrawlTrigger.manual, status=CrawlStatus.pending)
    db_session.add(job)
    db_session.flush()
    db_session.add(PageSnapshot(page_id=page.id, crawl_job_id=job.id, fetched_at=now, title=title, headings_json=headings))
    db_session.flush()
    return site


def test_seed_confidence_depends_on_where_the_phrase_came_from(db_session):
    from app.keywords.discovery_service import _persist_seed_ideas
    from app.keywords.seed_generation import generate_seed_details
    from app.models.keyword_observation import KeywordObservation
    from datetime import date

    site = _site_with_page(db_session, {"h1": ["Knee Pain on the Stairs"], "h2": ["Exercises to build stair strength"]})
    db_session.add(KeywordObservation(website_id=site.id, query="knee pain physio rawalpindi", date=date.today(), clicks=1, impressions=20, ctr=0.05, average_position=8.0, country="PK"))
    db_session.flush()
    details = dict(generate_seed_details(db_session, site))
    assert details["knee pain physio rawalpindi"] == "gsc_query" and details["Exercises to build stair strength"] == "site_heading"
    ideas = {i.keyword: i for i in _persist_seed_ideas(db_session, site, list(details.items()), country="PK")}
    assert ideas["knee pain physio rawalpindi"].confidence == 1.0
    heading = ideas["Exercises to build stair strength"]
    assert heading.confidence == 0.3 and "not that people search for it" in heading.rationale and heading.evidence_json["origin"] == "site_heading"


def test_old_noisy_seed_is_removed_but_dismissed_or_search_console_ones_are_kept(db_session):
    from app.keywords.discovery_service import prune_stale_site_seeds
    from app.models.keyword_idea import (KeywordDataClassification, KeywordIdea, KeywordIdeaSource, KeywordIdeaStatus, SearchIntent)

    site = _site_with_page(db_session, {"h1": ["Knee Pain on the Stairs"], "h2": []})

    def idea(keyword, origin, status=KeywordIdeaStatus.new):
        row = KeywordIdea(website_id=site.id, keyword=keyword, search_intent=SearchIntent.informational, source=KeywordIdeaSource.seed,
                          data_classification=KeywordDataClassification.verified_first_party, country="PK", relevance=1.0, confidence=1.0,
                          rationale="x", evidence_json={"seed": True, **({"origin": origin} if origin else {})}, status=status)
        db_session.add(row)
        return row

    noisy, dismissed, gsc = idea("What usually helps", None), idea("Simple tests and clues", None, KeywordIdeaStatus.dismissed), idea("some real query", "gsc_query")
    db_session.flush()
    removed = prune_stale_site_seeds(db_session, site, [("Knee Pain on the Stairs", "site_h1")], country="PK")
    db_session.flush()
    left = {r.keyword for r in db_session.query(KeywordIdea).filter_by(website_id=site.id)}
    assert removed == 1 and "What usually helps" not in left and {"Simple tests and clues", "some real query"} <= left
