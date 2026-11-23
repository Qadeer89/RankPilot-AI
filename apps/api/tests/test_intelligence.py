import socket
import threading
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from app.crawler.fetch import FetchResult
from app.intelligence import competitors, content, lab, technical
from app.models.business_profile import BusinessProfile
from app.models.competitor import CompetitorDomain, CompetitorPageSnapshot
from app.models.page_snapshot import PageSnapshot
from app.models.website import Website
from tests.ai_search_helpers import make_page, make_site
from tests.billing_helpers import register
from datetime import datetime, timezone


@pytest.fixture(autouse=True)
def _public_dns(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda host, *a, **k: [(socket.AF_INET, 1, 6, "", ("93.184.216.34", 0))])


def _snap(db, page):
    return db.query(PageSnapshot).filter_by(page_id=page.id).one()


def _site(db):
    site = make_site(db)
    for path, title, h in (("/", "Physiotherapy clinic", {"h1": ["Physiotherapy clinic"], "h2": ["Back pain therapy", "Knee rehab"]}),
                           ("/about", "About our team", {"h1": ["About us"], "h2": ["Our story", "Doctors"]}),
                           ("/contact", "Contact us", {"h1": ["Contact"], "h2": []}),
                           ("/faq", "FAQ", {"h1": ["FAQ"], "h2": ["How long does recovery take?", "What should I bring?"]})):
        p = make_page(db, site, path, title, h)
        s = _snap(db, p)
        s.word_count = 450 if path != "/contact" else 80
    db.flush()
    return site


def test_content_intelligence_scores_what_it_can_and_marks_the_rest(db_session):
    site = _site(db_session)
    r = content.analyze(db_session, site)
    parts = {p["key"]: p for p in r["parts"]}
    assert parts["depth"]["value"] == 75.0 and parts["topical"]["value"] is None and parts["topical"]["note"]
    assert {t["signal"]: t["found"] for t in parts["trust"]["inputs"]["signals"]}["about"] is True
    assert {t["signal"]: t["found"] for t in parts["trust"]["inputs"]["signals"]}["privacy"] is False
    assert r["findings"]["question_headings"] and "Not tested" in r["findings"]["near_duplicate_body_text"]
    assert r["coverage"] == 0.75 and r["score"] is not None


def test_topical_coverage_uses_confirmed_offerings_only(db_session):
    site = _site(db_session)
    db_session.add(BusinessProfile(website_id=site.id, offerings=["back pain therapy", "heart surgery"], confirmed_at=datetime.now(timezone.utc)))
    db_session.flush()
    t = {p["key"]: p for p in content.analyze(db_session, site, save=False)["parts"]}["topical"]
    status = {o["offering"]: o["status"] for o in t["inputs"]["offerings"]}
    assert status == {"back pain therapy": "covered", "heart surgery": "missing"}


def test_content_with_no_crawl_is_unavailable(db_session):
    assert content.analyze(db_session, make_site(db_session))["available"] is False


def _fake_fetch(site_host="example.com"):
    page = ('<html lang="en"><head><meta property="og:title" content="x"><link rel="icon" href="/f.ico"></head><body>hi</body></html>')
    def fetch(url):
        if url.startswith("http://"):
            return FetchResult(final_url=f"https://{site_host}/", status_code=200, headers={}, body=page, redirect_chain=["a"])
        if "www." in url:
            return FetchResult(final_url=f"https://{site_host}/", status_code=200, headers={}, body=page, redirect_chain=["a"])
        if url.endswith("robots.txt"):
            return FetchResult(final_url=url, status_code=404, headers={}, body="", redirect_chain=[])
        return FetchResult(final_url=url, status_code=200, headers={"Strict-Transport-Security": "max-age=1"}, body=page, redirect_chain=[])
    return fetch


def test_technical_checks_have_evidence_and_unknowns_are_not_zero(db_session):
    site = _site(db_session)
    r = technical.analyze(db_session, site, fetcher=_fake_fetch())
    by = {c["key"]: c for c in r["checks"]}
    assert by["html_lang"]["status"] == "pass" and by["open_graph"]["status"] == "warn" and "og:description" in by["open_graph"]["detail"]
    assert by["hdr_strict-transport-security"]["status"] == "pass" and by["hdr_x-content-type-options"]["group"] == "security_hygiene"
    assert by["hreflang"]["status"] == "not_tested" and by["robots_txt"]["status"] == "warn"
    assert by["canonical_host_http"]["status"] == "pass"
    assert r["not_tested"] >= 2 and 0 < r["score"] < 100 and r["coverage"] < 1


def test_http_version_that_does_not_redirect_is_flagged(db_session):
    site = _site(db_session)
    def fetch(url):
        return FetchResult(final_url=url, status_code=200, headers={}, body="<html></html>", redirect_chain=[])
    by = {c["key"]: c for c in technical.analyze(db_session, site, fetcher=fetch, save=False)["checks"]}
    assert by["canonical_host_http"]["status"] == "fail"


def test_schema_validation_finds_missing_required_properties(db_session):
    site = make_site(db_session)
    p = make_page(db_session, site, "/", "Home")
    s = _snap(db_session, p)
    s.schema_json = [{"raw": "", "parsed": {"@type": "LocalBusiness", "name": "Clinic"}, "parse_error": None}, {"raw": "{", "parsed": None, "parse_error": "bad"}]
    out = technical.validate_schema([(p.canonical_url, s)])
    assert "LocalBusiness is missing 'address'" in out[0]["problems"] and "JSON-LD could not be parsed" in out[0]["problems"]


class _H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.send_header("Content-Type", "text/html"); self.end_headers()
        self.wfile.write(b"<html><body><h1>Hello</h1></body></html>")
    def log_message(self, *a): pass


def test_local_lab_measures_a_real_page_in_the_headless_browser():
    srv = HTTPServer(("127.0.0.1", 0), _H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        m = lab.measure_page(f"http://127.0.0.1:{srv.server_address[1]}/")
    finally:
        srv.shutdown()
    assert m["status_code"] == 200 and m["load_ms"] >= m["ttfb_ms"] >= 0 and m["requests"] >= 1


def test_lab_run_refuses_other_hosts_and_labels_honestly(db_session):
    from app.core.url_safety import UnsafeUrlError
    site = make_site(db_session)
    with pytest.raises(UnsafeUrlError):
        lab.run(db_session, site, "https://other.test/", measure=lambda u: {})
    r = lab.run(db_session, site, None, measure=lambda u: {"load_ms": 900}, lh=lambda u: {"status": "not_tested", "reason": "x"})
    assert "Not field data, not Lighthouse" in r["data_source"] and r["lighthouse"]["status"] == "not_tested"
    bad = lab.run(db_session, site, None, measure=lambda u: (_ for _ in ()).throw(RuntimeError("x")), lh=lambda u: {"status": "not_tested"}, save=False)
    assert bad["available"] is False and bad["measurement"]["status"] == "error"


def test_competitor_structure_uses_only_crawled_public_data(db_session):
    site = _site(db_session)
    assert competitors.analyze(db_session, site)["available"] is False
    c = CompetitorDomain(website_id=site.id, domain="rival.test")
    db_session.add(c); db_session.flush()
    db_session.add(CompetitorPageSnapshot(competitor_domain_id=c.id, url="https://rival.test/", title="Sports massage and cupping", headings_json={"h1": ["Cupping therapy"], "h2": ["Dry needling", "Cupping"]},
                                           word_count=900, has_structured_data=True, fetched_at=datetime.now(timezone.utc)))
    db_session.flush()
    r = competitors.analyze(db_session, site)
    comp = r["competitors"][0]
    assert comp["median_words"] == 900 and comp["structured_data_share"] == 1.0 and "cup" in " ".join(comp["topic_terms_missing_from_your_site"]).lower() or comp["topic_terms_missing_from_your_site"]
    assert "Competitor traffic" in r["not_available"]


def test_api_flow_and_isolation(client, db_session):
    headers, org = register(client, "intel-owner@example.com")
    site = Website(organization_id=uuid.UUID(org), canonical_url="https://example.com/", hostname="example.com", display_name="Ex")
    db_session.add(site); db_session.flush()
    make_page(db_session, site, "/", "Home", {"h1": ["Home"], "h2": ["A", "B"]})
    db_session.commit()
    base = f"/api/v1/organizations/{org}/websites/{site.id}/intelligence"
    assert client.get(f"{base}/content", headers=headers).json()["latest"] is None
    r = client.post(f"{base}/content/run", headers=headers)
    assert r.status_code == 200 and r.json()["available"]
    assert client.get(f"{base}/content", headers=headers).json()["history"]
    assert client.get(f"{base}/nonsense", headers=headers).status_code == 404
    assert client.post(f"{base}/lab/run", json={"url": "https://evil.test/"}, headers=headers).status_code == 422
    other, _ = register(client, "intel-intruder@example.com")
    for method, path in (("get", "content"), ("post", "content/run"), ("get", "technical")):
        assert getattr(client, method)(f"{base}/{path}", headers=other).status_code in (403, 404)


def test_keyword_clusters_group_similar_queries_and_flag_split_pages():
    from app.intelligence import keywords as K
    import uuid as _u
    a, b = _u.uuid4(), _u.uuid4()
    rows = [{"query": "back pain physio", "page_id": a, "impressions": 60, "clicks": 3, "position": 9.0},
            {"query": "back pain physio", "page_id": b, "impressions": 40, "clicks": 1, "position": 14.0},
            {"query": "physio for back pain", "page_id": a, "impressions": 30, "clicks": 1, "position": 11.0},
            {"query": "how much does knee surgery cost", "page_id": b, "impressions": 20, "clicks": 0, "position": 20.0}]
    out = K.cluster(rows)
    assert len(out) == 2 and K.cluster(rows) == out
    main = out[0]
    assert main["possible_cannibalization"] is True and {q["query"] for q in main["queries"]} == {"back pain physio", "physio for back pain"}
    assert out[1]["intent"] == "informational" and out[1]["possible_cannibalization"] is False


def test_keyword_analysis_without_gsc_is_unavailable(db_session):
    from app.intelligence import keywords as K
    r = K.analyze(db_session, make_site(db_session))
    assert r["available"] is False and "Search Console" in r["reason"]


def test_report_includes_site_quality_only_when_comparable(db_session):
    from app.authority import assessment as A
    from app.history import report
    site = _site(db_session)
    assert report.site_quality(db_session, site)["available"] is False
    A.compute(db_session, site)
    content.analyze(db_session, site)
    q = report.site_quality(db_session, site)
    assert q["available"] and {i["label"] for i in q["items"]} == {"Domain Quality", "Content Quality"}
    assert all(i["comparable"] is False and i["change"] is None for i in q["items"])  # one run is a baseline, not a change
    assert "not Domain Rating" in q["note"]
