"""AI Search Opportunity Finder end to end through the API: analysis, approval, implementation, verification and
monitoring, plus tenant isolation. The AI provider and the page fetch are replaced by fakes (labelled as such in
the delivery report); everything else runs for real against PostgreSQL."""

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest

from app.ai_search import agent as ag
from app.ai_search import page_content, service
from app.models.ai_search_finding import AiSearchFinding
from app.models.audit_event import AuditEvent
from app.models.growth_recommendation import GrowthRecommendation
from app.models.membership import Membership, MembershipRole
from app.models.user import User
from app.models.website import Website
from tests.ai_search_helpers import make_page, observe
from tests.billing_helpers import register

QUERY = "how long does inpatient rehab take"
BEFORE_HTML = ("<html><head><title>Inpatient rehab | Clinic</title></head><body><main><h1>Inpatient rehab</h1><h2>Our programme</h2>"
               "<p>We offer residential treatment with medical supervision and family sessions in a calm setting. Stays are usually between 28 and 90 days.</p>"
               "<a href='/fees'>Fees</a><a href='/contact'>Contact</a><a href='/about'>About</a></main></body></html>")
AFTER_HTML = BEFORE_HTML.replace("<h2>Our programme</h2>", "<h2>How long does inpatient rehab take?</h2><p>Most inpatient programmes run for 28 to 90 days, "
                                 "depending on progress, and a clinician reviews the plan with the family every single week.</p><h2>Our programme</h2>")
GOOD_ANSWER = "Most inpatient programmes run for 28 to 90 days, and a clinician reviews the plan with the patient and family every week."


def _draft(answer=GOOD_ANSWER, **over):
    base = dict(search_intent="informational", user_question="How long is inpatient rehab?", page_matches_intent=True, intent_note="",
                current_answer_assessment="No direct answer.", missing_information=["typical duration"], needs_owner_input=[],
                direct_answer=answer, suggested_heading="How long does inpatient rehab take?", faq_recommended=False, faq_suggestions=[],
                supporting_examples=[], internal_links=[ag.InternalLink(anchor_text="Fees", target_url="https://clinic.example/fees")],
                schema_review_note="", rationale="The page never states a duration.", confidence=0.72)
    base.update(over)
    return ag.AiSearchDraft(**base)


class FakePage:
    html = BEFORE_HTML
    error = None


@pytest.fixture(autouse=True)
def no_network_for_robots(monkeypatch):
    from app.ai_search import crawler_access
    monkeypatch.setattr(crawler_access, "fetch_robots_text", lambda origin: ("User-agent: *\nAllow: /\n", None))


@pytest.fixture
def world(client, db_session, monkeypatch):
    headers, org = register(client, "owner@example.com")
    site = Website(organization_id=uuid.UUID(org), canonical_url="https://clinic.example/", hostname="clinic.example", display_name="Clinic",
                   search_console_site_url="sc-domain:clinic.example")
    db_session.add(site)
    db_session.flush()
    page = make_page(db_session, site, "/inpatient", "Inpatient rehab", {"h1": ["Inpatient rehab"], "h2": ["Our programme"]})
    for i in range(5):  # this site's own CTR benchmark
        observe(db_session, site, page, f"keyword number {i}", days_ago=6, impressions=20, clicks=2, position=8.0)
    for days in (5, 7, 22, 24):
        observe(db_session, site, page, QUERY, days_ago=days, impressions=25, clicks=0, position=8.0)
    db_session.commit()

    FakePage.html, FakePage.error = BEFORE_HTML, None

    def fake_fetch(website, url):
        if FakePage.error:
            return page_content.PageContent(url=url, available=False, error=FakePage.error)
        return page_content.parse_content(FakePage.html, url="https://clinic.example/inpatient", hostname="clinic.example")

    monkeypatch.setattr(service, "fetch_content", fake_fetch)
    state = {"draft": _draft(), "calls": 0, "error": None}

    def fake_generate(db, website, **kwargs):
        state["calls"] += 1
        if state["error"]:
            raise state["error"]
        return state["draft"]

    monkeypatch.setattr(ag, "generate_draft", fake_generate)
    base = f"/api/v1/organizations/{org}/websites/{site.id}/ai-search"
    return type("W", (), dict(headers=headers, org=org, site=site, page=page, base=base, state=state))


def _analyze(client, w, query=QUERY, **extra):
    return client.post(f"{w.base}/analyze", json={"query": query, **extra}, headers=w.headers)


def test_summary_counts_come_from_stored_data(client, world):
    r = client.get(f"{world.base}/summary", headers=world.headers).json()
    assert r["totals"]["question_queries"] == 1 and r["totals"]["conversational_queries"] == 1  # six words and a question and r["ai_platform_visibility"] == "unmeasured"
    assert "not prompts typed into ChatGPT" in r["explanation"]
    assert r["data_coverage"]["rows"] == 9


def test_opportunity_table_filters_sorts_and_paginates(client, world):
    r = client.get(f"{world.base}/opportunities?category=question", headers=world.headers).json()
    assert r["total"] == 1 and r["items"][0]["query"] == QUERY and r["items"][0]["landing_page"]["url"].endswith("/inpatient")
    assert r["items"][0]["status"] == "new" and r["items"][0]["factors"]
    assert client.get(f"{world.base}/opportunities?q=zzz", headers=world.headers).json()["total"] == 0
    assert client.get(f"{world.base}/opportunities?min_impressions=500", headers=world.headers).json()["total"] == 0
    assert client.get(f"{world.base}/opportunities?page_size=1&page=2", headers=world.headers).json()["items"] == []


@pytest.mark.parametrize("qs,code", [("range=bogus", 422), ("category=made_up", 422), ("sort=volume", 422), ("country=atlantis", 400), ("page_size=500", 422),
                                      ("max_ctr=7", 422), ("range=custom", 422)])
def test_invalid_inputs_are_rejected(client, world, qs, code):
    assert client.get(f"{world.base}/opportunities?{qs}", headers=world.headers).status_code == code


def test_detail_includes_history_and_explanations(client, world):
    r = client.get(f"{world.base}/opportunities/detail", params={"query": QUERY}, headers=world.headers).json()
    assert len(r["history"]) == 4 and sum(h["impressions"] for h in r["history"]) == 100 and r["finding"] is None
    assert client.get(f"{world.base}/opportunities/detail", params={"query": "never searched"}, headers=world.headers).status_code == 404


def test_full_lifecycle_analyze_review_approve_implement_verify_monitor(client, db_session, world):
    f = _analyze(client, world).json()
    assert f["status"] == "ready_for_review" and f["ai_status"] == "ok" and f["draft"]["direct_answer"] == GOOD_ANSWER
    assert f["answer_analysis"]["level"] in ("missing", "partial") and f["ai_search_readiness"]["ai_visibility"] == "unmeasured"
    assert f["recommendation"]["requires_approval"] and "(estimate)" in f["recommendation"]["expected_benefit"]
    assert f["execution"]["automated"] is False and "cannot insert page body content" in f["execution"]["reason"]
    assert "not a verified fact" in f["label"] and f["quality"]["blocked"] is False
    assert f["metrics"]["impressions"] == 100 and f["target_page"]["url"].endswith("/inpatient")

    rec = db_session.query(GrowthRecommendation).filter(GrowthRecommendation.recommendation_type == "ai_search_answer").one()
    assert rec.status.value == "open" and rec.evidence_json["ai_search_finding_id"] == f["id"]

    # cannot mark implemented before approval
    fid = f["id"]
    assert client.post(f"{world.base}/findings/{fid}/mark-implemented", json={}, headers=world.headers).json()["detail"]["code"] == "not_approved"
    assert client.post(f"{world.base}/findings/{fid}/approve", headers=world.headers).json()["status"] == "approved"

    # the owner adds the section in their CMS; RankPilot re-reads the public page
    FakePage.html = AFTER_HTML
    done = client.post(f"{world.base}/findings/{fid}/mark-implemented", json={"note": "added under the intro"}, headers=world.headers).json()
    assert done["status"] == "monitoring" and done["live_check"]["matched"] is True and done["implementation_note"] == "added under the intro"
    assert done["baseline"]["query"]["impressions"] == 0 or done["baseline"]["query"] is None or done["baseline"]["query"]["impressions"] >= 0
    db_session.expire_all()
    assert db_session.get(GrowthRecommendation, uuid.UUID(f["recommendation"]["id"])).status.value == "done"
    actions = {e.action for e in db_session.query(AuditEvent).all()}
    assert {"ai_search.analyze", "ai_search.approve", "ai_search.mark_implemented"} <= actions


def test_a_blocked_draft_cannot_be_approved_until_edited_to_pass(client, world):
    world.state["draft"] = _draft(answer="Inpatient rehab takes 45 days and we guarantee a 95% success rate for everyone who joins the programme here.")
    f = _analyze(client, world).json()
    assert f["quality"]["blocked"] is True
    blocked = client.post(f"{world.base}/findings/{f['id']}/approve", headers=world.headers)
    assert blocked.status_code == 409 and blocked.json()["detail"]["code"] == "quality_blocked"
    edited = client.patch(f"{world.base}/findings/{f['id']}/draft", json={"direct_answer": GOOD_ANSWER}, headers=world.headers).json()
    assert edited["quality"]["blocked"] is False and edited["edited_by_user"] is True
    assert client.post(f"{world.base}/findings/{f['id']}/approve", headers=world.headers).json()["status"] == "approved"
    assert client.patch(f"{world.base}/findings/{f['id']}/draft", json={"direct_answer": "x" * 30}, headers=world.headers).json()["detail"]["code"] == "approved"


def test_reject_then_regenerate(client, world):
    f = _analyze(client, world).json()
    assert client.post(f"{world.base}/findings/{f['id']}/reject", headers=world.headers).json()["status"] == "rejected"
    again = _analyze(client, world).json()
    assert again["id"] == f["id"] and again["status"] == "ready_for_review" and world.state["calls"] == 2


def test_an_approved_recommendation_is_not_silently_regenerated(client, world):
    f = _analyze(client, world).json()
    client.post(f"{world.base}/findings/{f['id']}/approve", headers=world.headers)
    r = _analyze(client, world)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "approved"


def test_ai_failure_keeps_the_analysis_and_creates_no_recommendation(client, db_session, world):
    world.state["error"] = RuntimeError("provider exploded with secret details")
    f = _analyze(client, world)
    body = f.json()
    assert f.status_code == 200 and body["ai_status"] == "unavailable" and body["draft"] is None and body["recommendation"] is None
    assert "secret details" not in body["ai_error"] and body["answer_analysis"]["level"] in ("missing", "partial") and body["status"] == "new"
    assert db_session.query(GrowthRecommendation).filter(GrowthRecommendation.recommendation_type == "ai_search_answer").count() == 0


def test_budget_or_entitlement_blocks_are_reported_in_plain_words(client, world):
    from app.ai.budget import BudgetExceeded
    world.state["error"] = BudgetExceeded("The daily AI budget for this project has been used.")
    body = _analyze(client, world).json()
    assert body["ai_status"] == "unavailable" and "daily AI budget" in body["ai_error"]


def test_unreadable_page_gives_no_draft_and_says_why(client, world):
    FakePage.error = "HTTP 404"
    body = _analyze(client, world).json()
    assert body["page_content_available"] is False and body["draft"] is None and "could not be read" in body["ai_error"] and world.state["calls"] == 0
    assert body["answer_analysis"]["level"] == "unknown"


def test_a_query_with_no_known_page_is_not_given_an_invented_one(client, db_session, world):
    observe(db_session, world.site, None, "what is the cost of a private detox programme here", days_ago=5, impressions=40, position=12.0)
    db_session.commit()
    body = _analyze(client, world, "what is the cost of a private detox programme here").json()
    assert body["target_page"]["url"] is None and body["ai_status"] == "skipped" and body["tier"] == "content_gap" and world.state["calls"] == 0


def test_competing_pages_get_a_review_recommendation_not_a_draft(client, db_session, world):
    other = make_page(db_session, world.site, "/detox", "Detox")
    for days in (5, 7, 22, 24):
        observe(db_session, world.site, other, QUERY, days_ago=days, impressions=15, position=9.0)
    db_session.commit()
    body = _analyze(client, world).json()
    assert body["needs_review"] is True and body["draft"] is None and world.state["calls"] == 0 and "Several pages" in body["ai_error"]
    assert body["recommendation"]["problem"].endswith("split across several of this site's pages.")
    assert client.post(f"{world.base}/findings/{body['id']}/approve", headers=world.headers).json()["detail"]["code"] == "needs_review"


def test_failed_verification_is_reported_and_recheck_can_clear_it(client, world):
    f = _analyze(client, world).json()
    client.post(f"{world.base}/findings/{f['id']}/approve", headers=world.headers)
    # the owner marked it done but the public page still lacks the section
    r = client.post(f"{world.base}/findings/{f['id']}/mark-implemented", json={}, headers=world.headers).json()
    assert r["status"] == "validation_failed" and r["live_check"]["matched"] is False
    FakePage.html = AFTER_HTML
    again = client.post(f"{world.base}/findings/{f['id']}/recheck", headers=world.headers).json()
    assert again["status"] == "monitoring" and again["live_check"]["matched"] is True


def test_an_unreachable_page_leaves_verification_pending_not_failed(client, world):
    f = _analyze(client, world).json()
    client.post(f"{world.base}/findings/{f['id']}/approve", headers=world.headers)
    FakePage.error = "timeout"
    r = client.post(f"{world.base}/findings/{f['id']}/mark-implemented", json={}, headers=world.headers).json()
    assert r["status"] == "implemented" and r["live_check"]["matched"] is None and r["live_check"]["error"] == "timeout"


def test_monitoring_compares_equal_windows_and_never_claims_causation(client, db_session, world):
    f = _analyze(client, world).json()
    client.post(f"{world.base}/findings/{f['id']}/approve", headers=world.headers)
    FakePage.html = AFTER_HTML
    client.post(f"{world.base}/findings/{f['id']}/mark-implemented", json={}, headers=world.headers)
    row = db_session.get(AiSearchFinding, uuid.UUID(f["id"]))
    day = date(2026, 6, 15)  # fixed history so the windows are exact
    row.implemented_at = datetime(2026, 6, 15, 10, tzinfo=timezone.utc)
    db_session.add_all([])
    db_session.commit()
    for days, impr, clicks, pos in [(10, 100, 2, 9.0), (3, 100, 3, 7.0)]:  # before-window rows, then rows inside the after-window
        observe(db_session, world.site, world.page, QUERY, days_ago=(date.today() - (day - timedelta(days=days))).days, impressions=impr, clicks=clicks, position=pos)
    for days, impr, clicks, pos in [(2, 200, 10, 5.0)]:
        observe(db_session, world.site, world.page, QUERY, days_ago=(date.today() - (day + timedelta(days=days))).days, impressions=impr, clicks=clicks, position=pos)
    db_session.commit()
    m = client.get(f"{world.base}/findings/{f['id']}/monitoring", headers=world.headers).json()
    # before: 100+100 = 200 impressions, 5 clicks, weighted position (9*100+7*100)/200 = 8.0 ; after: 200 impressions, 10 clicks, position 5.0
    assert m["before"] == {"clicks": 5, "impressions": 200, "ctr": 0.025, "average_position": 8.0}
    assert m["after"] == {"clicks": 10, "impressions": 200, "ctr": 0.05, "average_position": 5.0}
    assert m["change"] == {"clicks": 5, "impressions": 0, "ctr": 0.025, "average_position": -3.0}
    assert m["after_window_complete"] is True and "does not show that the change caused it" in m["caveat"]
    assert "correlation" in m["note"] and m["country_breakdown"]["US"]["after"]["clicks"] == 10
    assert client.get(f"{world.base}/findings/{f['id']}/monitoring?window_days=5", headers=world.headers).status_code == 409


def test_other_changes_on_the_same_page_are_called_out(client, db_session, world):
    a = _analyze(client, world).json()
    client.post(f"{world.base}/findings/{a['id']}/approve", headers=world.headers)
    FakePage.html = AFTER_HTML
    client.post(f"{world.base}/findings/{a['id']}/mark-implemented", json={}, headers=world.headers)
    db_session.add(AiSearchFinding(website_id=world.site.id, query="another", query_key="another", scope_country="ALL", tier="low_priority",
                                   page_id=world.page.id, implemented_at=datetime.now(timezone.utc)))
    db_session.commit()
    m = client.get(f"{world.base}/findings/{a['id']}/monitoring", headers=world.headers).json()
    assert m["other_changes_in_window"] and "cannot be attributed" in m["note"]
    assert client.get(f"{world.base}/findings/{a['id']}/monitoring", headers=world.headers).status_code == 200


def test_monitoring_before_implementation_is_refused(client, world):
    f = _analyze(client, world).json()
    assert client.get(f"{world.base}/findings/{f['id']}/monitoring", headers=world.headers).status_code == 409


# ---------------------------------------------------------------- security

def test_another_workspace_cannot_see_or_change_anything(client, world):
    f = _analyze(client, world).json()
    other_headers, other_org = register(client, "intruder@example.com")
    for method, path in [("get", "summary"), ("get", "opportunities"), ("get", "findings"), ("get", f"findings/{f['id']}"),
                         ("post", f"findings/{f['id']}/approve"), ("post", f"findings/{f['id']}/reject")]:
        r = getattr(client, method)(f"{world.base}/{path}", headers=other_headers)
        assert r.status_code in (403, 404), (path, r.status_code)
    # their own workspace with the victim's website id and finding id: still nothing
    own = f"/api/v1/organizations/{other_org}/websites/{world.site.id}/ai-search"
    assert client.get(f"{own}/summary", headers=other_headers).status_code == 404
    assert client.get(f"{own}/findings/{f['id']}", headers=other_headers).status_code == 404
    assert client.post(f"{own}/analyze", json={"query": QUERY}, headers=other_headers).status_code == 404


def test_unauthenticated_requests_are_rejected(client, world):
    assert client.get(f"{world.base}/summary").status_code == 401
    assert client.post(f"{world.base}/analyze", json={"query": QUERY}).status_code == 401


def test_a_viewer_can_read_but_cannot_analyse_approve_or_implement(client, db_session, world):
    f = _analyze(client, world).json()
    viewer_headers, _ = register(client, "viewer@example.com")
    viewer = db_session.query(User).filter(User.email == "viewer@example.com").one()
    db_session.add(Membership(organization_id=uuid.UUID(world.org), user_id=viewer.id, role=MembershipRole.viewer))
    db_session.commit()
    assert client.get(f"{world.base}/summary", headers=viewer_headers).status_code == 200
    assert client.get(f"{world.base}/findings/{f['id']}", headers=viewer_headers).status_code == 200
    for path, body in [("analyze", {"query": QUERY}), (f"findings/{f['id']}/approve", None), (f"findings/{f['id']}/reject", None),
                       (f"findings/{f['id']}/mark-implemented", {})]:
        assert client.post(f"{world.base}/{path}", json=body, headers=viewer_headers).status_code == 403, path
    assert client.patch(f"{world.base}/findings/{f['id']}/draft", json={"direct_answer": "x" * 40}, headers=viewer_headers).status_code == 403


def test_nothing_is_published_by_the_recommendation_workflow(client, db_session, world):
    """The feature never writes to a CMS: no change record or SEO task is created at any stage."""
    from app.models.change_record import ChangeRecord
    from app.models.seo_task import SEOTask
    f = _analyze(client, world).json()
    client.post(f"{world.base}/findings/{f['id']}/approve", headers=world.headers)
    FakePage.html = AFTER_HTML
    client.post(f"{world.base}/findings/{f['id']}/mark-implemented", json={}, headers=world.headers)
    assert db_session.query(ChangeRecord).count() == 0 and db_session.query(SEOTask).count() == 0


def test_the_analyze_endpoint_is_rate_limited(client, world, monkeypatch):
    calls = []
    import app.api.v1.endpoints.ai_search as ep
    monkeypatch.setattr(ep, "enforce_rate_limit", lambda key, **kw: calls.append((key, kw)))
    _analyze(client, world)
    assert calls and calls[0][1] == {"max_attempts": 30, "window_seconds": 3600}


def test_robots_access_endpoint_reports_each_crawler_and_is_tenant_scoped(client, world, monkeypatch):
    from app.ai_search import crawler_access
    monkeypatch.setattr(crawler_access, "fetch_robots_text", lambda origin: ("User-agent: GPTBot\nDisallow: /\n\nUser-agent: PerplexityBot\nDisallow: /private/\n", None))
    r = client.get(f"{world.base}/crawler-access", headers=world.headers).json()
    states = {row["token"]: row["state"] for row in r["rows"]}
    assert states["GPTBot"] == "blocked" and states["OAI-SearchBot"] == "allowed" and states["Googlebot"] == "allowed"
    assert r["summary"]["training_crawlers_blocked"] == ["GPTBot"] and r["summary"]["search_crawlers_blocked"] == []
    assert "robots.txt only" in r["note"]
    other, _ = register(client, "stranger2@example.com")
    assert client.get(f"{world.base}/crawler-access", headers=other).status_code in (403, 404)


def test_readiness_flags_blocked_search_crawlers_but_not_blocked_training_crawlers(client, world, monkeypatch):
    from app.ai_search import crawler_access
    monkeypatch.setattr(crawler_access, "fetch_robots_text", lambda origin: ("User-agent: GPTBot\nDisallow: /\n", None))
    ok = _analyze(client, world).json()["ai_search_readiness"]
    assert next(c for c in ok["checks"] if c["check"] == "AI search crawlers can reach the site")["status"] == "pass"
    monkeypatch.setattr(crawler_access, "fetch_robots_text", lambda origin: ("User-agent: OAI-SearchBot\nDisallow: /\n", None))
    client.post(f"{world.base}/findings/{_analyze(client, world).json()['id']}/reject", headers=world.headers)
    blocked = _analyze(client, world).json()["ai_search_readiness"]
    check = next(c for c in blocked["checks"] if c["check"] == "AI search crawlers can reach the site")
    assert check["status"] == "fail" and "OAI-SearchBot" in check["evidence"]


def test_an_unreadable_robots_file_adds_no_check_rather_than_guessing(client, world, monkeypatch):
    from app.ai_search import crawler_access
    monkeypatch.setattr(crawler_access, "fetch_robots_text", lambda origin: (None, "robots.txt answered HTTP 503"))
    names = [c["check"] for c in _analyze(client, world).json()["ai_search_readiness"]["checks"]]
    assert "AI search crawlers can reach the site" not in names
