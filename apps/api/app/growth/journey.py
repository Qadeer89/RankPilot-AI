"""The customer's growth journey: where they are, what data exists, and what to do next.

The dashboard adapts to the data that is genuinely available. With no Google data connected it shows the crawl-based
baseline and says what connecting Google will add; it never shows traffic, rankings, impressions or revenue it does
not have."""

from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.competitors.service import CompetitorDomain  # noqa: F401  (imported for the model registry)
from app.execution.connections import get_connected_content_connector
from app.growth import unified
from app.history import snapshots as snap
from app.models.business_profile import BusinessProfile
from app.models.competitor import CompetitorDomain
from app.models.ga4_daily_metric import Ga4DailyMetric
from app.models.history import ProjectMetricHistory
from app.models.keyword_idea import KeywordIdea
from app.models.keyword_observation import KeywordObservation
from app.models.seo_finding import FindingSeverity, FindingStatus, SEOFinding
from app.models.website import Website

BASELINE_READY = "Your initial SEO baseline is ready. Connect Google Search Console and Analytics to measure actual search performance and organic traffic."
ANALYSING = "We are analysing your website. Your initial SEO baseline appears here as soon as the first crawl finishes."
GSC_WAITING = "Search Console is connected. Real search performance appears after the first data sync."
CONNECTED = "Your SEO baseline and Google performance data are available. Compare periods to see how organic visibility is changing."


def _has_gsc_data(db: Session, website: Website) -> bool:
    return bool(db.query(ProjectMetricHistory.id).filter(ProjectMetricHistory.website_id == website.id).first()
                or db.query(KeywordObservation.id).filter(KeywordObservation.website_id == website.id).first())


def build(db: Session, website: Website) -> dict:
    snap.ensure_history(db, website)
    baseline, latest = snap.baseline_snapshot(db, website.id), snap.latest_crawl_snapshot(db, website.id)
    gsc_connected, ga4_connected = bool(website.search_console_site_url), bool(website.ga4_property_id)
    gsc_data = _has_gsc_data(db, website)
    gsc_totals = bool(db.query(ProjectMetricHistory.id).filter(ProjectMetricHistory.website_id == website.id).first())
    ga4_data = bool(db.query(Ga4DailyMetric.id).filter(Ga4DailyMetric.website_id == website.id).first())
    profile = db.query(BusinessProfile).filter(BusinessProfile.website_id == website.id).one_or_none()
    cms = get_connected_content_connector(db, website)
    competitors = db.query(func.count(CompetitorDomain.id)).filter(CompetitorDomain.website_id == website.id).scalar() or 0
    ideas = db.query(func.count(KeywordIdea.id)).filter(KeywordIdea.website_id == website.id).scalar() or 0
    open_findings = db.query(SEOFinding).filter(SEOFinding.website_id == website.id, SEOFinding.status == FindingStatus.open)
    critical = open_findings.filter(SEOFinding.severity == FindingSeverity.critical).count()
    items = unified.build(db, website)
    pending = [i for i in items if i["stage"] in ("recommended", "reopened")]

    if baseline is None:
        mode, message = "analysing", ANALYSING
    elif not (gsc_data or ga4_data):
        mode, message = ("baseline", GSC_WAITING if gsc_connected or ga4_connected else BASELINE_READY)
    else:
        mode, message = "connected", CONNECTED

    def panel(name: str, available: bool, source: str, why: str | None) -> dict:
        return {"panel": name, "available": available, "source": source, "reason": None if available else why}

    panels = [
        panel("Website health and issues", baseline is not None, "RankPilot crawl", "Waiting for the first crawl to finish."),
        panel("Keyword opportunities", ideas > 0, "AI-generated ideas (not verified search data)", "Run keyword discovery to generate ideas."),
        panel("Competitor content gaps", competitors > 0, "Public competitor pages", "Add competitors to compare publicly visible content."),
        panel("Organic clicks, impressions, position", gsc_data,
              "Google Search Console" if gsc_totals or not gsc_data else "Google Search Console (query-level rows only; daily totals are collected on the next sync)", "Requires Google Search Console." if not gsc_connected else "Waiting for the first sync."),
        panel("Organic sessions and conversions", ga4_data, "Google Analytics", "Requires Google Analytics." if not ga4_connected else "Waiting for the first sync."),
    ]

    actions: list[dict] = []

    def add(key: str, text: str, detail: str | None = None) -> None:
        actions.append({"key": key, "text": text, "detail": detail})

    if baseline is None:
        add("first_crawl", "Wait for the first crawl to finish", "It runs automatically.")
    if profile is None or profile.confirmed_at is None:
        add("business_profile", "Confirm your business profile", "It helps RankPilot suggest relevant search topics.")
    if not gsc_connected:
        add("connect_gsc", "Connect Google Search Console", "It provides verified clicks, impressions, CTR and average position.")
    if not ga4_connected:
        add("connect_ga4", "Connect Google Analytics", "It provides organic sessions and conversions.")
    if critical:
        add("fix_critical", f"Fix {critical} critical issue(s)", "These can stop pages from being found or understood.")
    if pending:
        add("review_recommendations", f"Review {len(pending)} recommendation(s)", "Approve, edit or dismiss each one.")
    if cms is None:
        add("connect_cms", "Connect your CMS to apply approved changes from RankPilot", None)
    if competitors == 0:
        add("add_competitors", "Add competitors to find content gaps", "Only their public pages are read.")
    if ideas == 0:
        add("keyword_discovery", "Generate keyword ideas", "They are AI-generated suggestions, not verified search volume.")
    return {
        "mode": mode, "message": message, "baseline": ({"taken_at": baseline.created_at.isoformat(), "reconstructed": baseline.reconstructed} if baseline else None),
        "last_analysis_at": latest.created_at.isoformat() if latest else None,
        "integrations": {"google_search_console": {"connected": gsc_connected, "has_data": gsc_data}, "ga4": {"connected": ga4_connected, "has_data": ga4_data},
                         "cms": cms.value if cms else None},
        "panels": panels, "next_actions": actions, "recommendations": unified.summarise(items),
        "expectations": "RankPilot analyses your website, identifies SEO opportunities, helps implement improvements and tracks your organic search performance. "
                        "Search engines decide rankings independently, so no result, ranking or traffic level is guaranteed.",
    }
