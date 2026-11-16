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
