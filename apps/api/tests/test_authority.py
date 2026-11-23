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


# ---- backlinks ----
from app.authority import backlinks as B  # noqa: E402
from app.crawler.fetch import FetchError, FetchResult  # noqa: E402


import socket  # noqa: E402

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _public_dns(monkeypatch):
    """The sandbox has no DNS; resolve every name to a public address so the real SSRF validation still runs."""
    real = socket.getaddrinfo
    def fake(host, *a, **k):
        try:
            return real(host, *a, **k) if host in ("127.0.0.1", "localhost") else [(socket.AF_INET, 1, 6, "", ("93.184.216.34", 0))]
        except socket.gaierror:
            return [(socket.AF_INET, 1, 6, "", ("93.184.216.34", 0))]
    monkeypatch.setattr(socket, "getaddrinfo", fake)


def _res(body, status=200, url="https://blog.test/post"):
    return FetchResult(final_url=url, status_code=status, headers={}, body=body, redirect_chain=[])


def test_find_links_captures_anchor_rel_location_and_ignores_other_hosts():
    html = ('<main><p><a href="https://www.example.com/pricing#x" rel="nofollow ugc">our pricing</a> <a href="https://other.com">no</a></p></main>'
            '<footer><a href="/about">own</a></footer>')
    out = B.find_links_to_site(html, "https://blog.test/post", "example.com")
    assert len(out) == 1 and out[0]["target_url"] == "https://www.example.com/pricing" and out[0]["is_nofollow"] is True
    assert out[0]["anchor_text"] == "our pricing" and out[0]["link_location"] == "content"


def test_add_rejects_own_site_private_and_duplicates(db_session):
    site = make_site(db_session)
    r = B.add_backlinks(db_session, site, ["https://blog.test/a", "https://blog.test/a", "https://example.com/x", "http://127.0.0.1/p"], "user_provided")
    assert r["added"] == 1 and len(r["rejected"]) == 2
    assert B.add_backlinks(db_session, site, ["https://blog.test/a"], "user_provided")["duplicates"] == 1


def test_check_history_new_changed_lost_and_outage_does_not_erase(db_session):
    site = make_site(db_session)
    B.add_backlinks(db_session, site, ["https://blog.test/post"], "user_provided")
    bl = db_session.query(B.Backlink).filter_by(website_id=site.id).one()
    live = '<p><a href="https://example.com/">Example</a></p>'
    B.check_backlink(db_session, site, bl, fetcher=lambda u: _res(live))
    assert bl.status == "live" and bl.anchor_text == "Example" and bl.last_live_at
    def boom(u): raise FetchError("timeout")
    B.check_backlink(db_session, site, bl, fetcher=boom)
    assert bl.status == "live"  # outage is not a lost link
    c = B.check_backlink(db_session, site, bl, fetcher=lambda u: _res("<p>nothing</p>"))
    assert bl.status == "link_removed" and bl.lost_at and any(ch["field"] == "status" for ch in c.changes_json)
    B.check_backlink(db_session, site, bl, fetcher=lambda u: _res(live.replace("Example", "Example Co")))
    assert bl.status == "live" and bl.lost_at is None and bl.anchor_text == "Example Co"
    assert db_session.query(B.BacklinkCheck).filter_by(backlink_id=bl.id).count() == 4


def test_referring_domain_analysis_counts_only_verified(db_session):
    site = make_site(db_session)
    B.add_backlinks(db_session, site, ["https://a.test/1", "https://a.test/2", "https://b.test/1"], "gsc_export")
    for bl in db_session.query(B.Backlink).filter_by(website_id=site.id):
        if bl.source_url.endswith("/2"):
            continue  # stays unchecked
        B.check_backlink(db_session, site, bl, fetcher=lambda u: _res('<a href="https://example.com/p">brand</a>', url=u))
    a = B.referring_domain_analysis(db_session, site)
    assert a["recorded"] == 3 and a["verified_live"] == 2 and a["unchecked"] == 1 and a["referring_domains"] == 2
    assert "not a count of every link" in a["label"]


# ---- API ----
import uuid  # noqa: E402

from app.models.website import Website  # noqa: E402
from tests.billing_helpers import register  # noqa: E402


@pytest.fixture
def world(client, db_session):
    headers, org = register(client, "authority-owner@example.com")
    site = Website(organization_id=uuid.UUID(org), canonical_url="https://example.com/", hostname="example.com", display_name="Ex")
    db_session.add(site); db_session.flush()
    for path in ("/", "/a", "/b"):
        make_page(db_session, site, path, f"Physiotherapy {path}")
    db_session.commit()
    return type("W", (), dict(headers=headers, org=org, site=site, base=f"/api/v1/organizations/{org}/websites/{site.id}"))


def test_api_authority_and_backlink_flow(client, world):
    g = client.get(f"{world.base}/authority", headers=world.headers).json()
    assert g["latest"] is None and "not Domain Rating" in g["disclaimer"] and g["empty_reason"]
    r = client.post(f"{world.base}/authority/refresh", headers=world.headers)
    assert r.status_code == 200 and r.json()["data_source"] == "RankPilot calculated"
    assert client.get(f"{world.base}/authority", headers=world.headers).json()["history"]
    imp = client.post(f"{world.base}/backlinks/import", json={"text": "https://blog.test/x, https://example.com/own", "source": "gsc_export"}, headers=world.headers).json()
    assert imp["added"] == 1 and len(imp["rejected"]) == 1
    assert client.post(f"{world.base}/backlinks/import", json={"text": "no urls here"}, headers=world.headers).status_code == 422
    assert client.post(f"{world.base}/backlinks/import", json={"urls": ["https://a.test"], "source": "public_page_scan"}, headers=world.headers).status_code == 422
    items = client.get(f"{world.base}/backlinks", headers=world.headers).json()
    assert items["items"][0]["status"] == "unchecked" and items["items"][0]["data_source"] == "Not checked"
    bid = items["items"][0]["id"]
    assert client.get(f"{world.base}/backlinks/{bid}/history", headers=world.headers).status_code == 200
    assert client.delete(f"{world.base}/backlinks/{bid}", headers=world.headers).status_code == 204


def test_api_tenant_isolation(client, world):
    other, _org2 = register(client, "authority-intruder@example.com")
    for method, path in (("get", "/authority"), ("post", "/authority/refresh"), ("get", "/backlinks"), ("post", "/backlinks/check")):
        resp = getattr(client, method)(f"{world.base}{path}", headers=other)
        assert resp.status_code in (403, 404), (path, resp.status_code)
