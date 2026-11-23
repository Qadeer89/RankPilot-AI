from datetime import datetime, timezone

from app.authority import assessment as A
from app.models.crawl_job import CrawlJob, CrawlTrigger
from app.models.page import IndexabilityState
from app.models.page_snapshot import PageSnapshot
from tests.ai_search_helpers import make_page, make_site


def _site_with_links(db):
    site = make_site(db)
    home = make_page(db, site, "/", "Physiotherapy clinic Lahore", {"h1": ["Physiotherapy clinic"]})
    a = make_page(db, site, "/back-pain", "Back pain physiotherapy", {"h1": ["Back pain"]})
    b = make_page(db, site, "/knee", "Knee physiotherapy", {"h1": ["Knee"]})
    orphan = make_page(db, site, "/orphan", "Physiotherapy orphan", {"h1": ["Orphan"]})
    snaps = {s.page_id: s for s in db.query(PageSnapshot).all() if s.page_id in {home.id, a.id, b.id, orphan.id}}
    snaps[home.id].internal_links_json = [a.normalized_url, b.normalized_url]
    snaps[a.id].internal_links_json = [b.normalized_url, home.normalized_url]
    snaps[b.id].internal_links_json = [a.normalized_url]
    for s in snaps.values():
        s.word_count = 500
    for p in (home, a, b, orphan):
        p.indexability_state = IndexabilityState.indexable
    db.flush()
    return site


def test_missing_data_is_not_available_never_zero(db_session):
    site = make_site(db_session)
    row = A.compute(db_session, site)
    assert row.domain_quality is None and row.confidence == "none"
    assert all(s["value"] is None for s in row.signals_json)


def test_signals_from_real_crawl_and_reproducible(db_session):
    site = _site_with_links(db_session)
    row = A.compute(db_session, site)
    by = {s["key"]: s for s in row.signals_json}
    assert by["internal_link_strength"]["inputs"]["orphan_pages"] == 1
    assert by["organic_visibility"]["status"] == "not_available"  # no Search Console data
    assert by["content_freshness"]["status"] == "not_available"
    assert 0 < row.domain_quality <= 100 and row.coverage < 1
    # re-deriving from the stored inputs gives the same numbers
    again = A.score_from_inputs(row.inputs_json)
    score, coverage, _ = A.combine(again)
    assert score == row.domain_quality and coverage == row.coverage


def test_compare_flags_formula_change_and_first_run(db_session):
    site = _site_with_links(db_session)
    first = A.compute(db_session, site)
    assert A.compare(None, first)["available"] is False
    job = CrawlJob(website_id=site.id, trigger=CrawlTrigger.manual)
    db_session.add(job); db_session.flush()
    second = A.compute(db_session, site, job.id)
    assert A.compute(db_session, site, job.id).id == second.id  # idempotent per crawl
    out = A.compare(first, second)
    assert out["available"] and out["domain_quality_change"] == 0
