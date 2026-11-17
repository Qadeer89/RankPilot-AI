import uuid
from datetime import date, datetime, timedelta, timezone

from app.models.crawl_job import CrawlJob, CrawlStatus, CrawlTrigger
from app.models.keyword_observation import KeywordObservation
from app.models.organization import Organization
from app.models.page import Page
from app.models.page_snapshot import PageSnapshot
from app.models.website import Website


def make_site(db, host="example.com"):
    org = Organization(name="AI Search Org", slug=f"ais-{uuid.uuid4().hex[:8]}")
    db.add(org)
    db.flush()
    site = Website(organization_id=org.id, canonical_url=f"https://{host}/", hostname=host, display_name=host,
                   search_console_site_url=f"sc-domain:{host}")
    db.add(site)
    db.flush()
    return site


def make_page(db, site, path="/guide", title="Guide", headings=None, with_snapshot=True):
    now = datetime.now(timezone.utc)
    page = Page(website_id=site.id, canonical_url=f"https://{site.hostname}{path}", normalized_url=f"https://{site.hostname}{path}",
                first_seen_at=now, last_seen_at=now, last_status_code=200)
    db.add(page)
    db.flush()
    if with_snapshot:
        crawl = db.query(CrawlJob).filter(CrawlJob.website_id == site.id).first()
        if crawl is None:
            crawl = CrawlJob(website_id=site.id, status=CrawlStatus.completed, trigger=CrawlTrigger.manual)
            db.add(crawl)
            db.flush()
        db.add(PageSnapshot(page_id=page.id, crawl_job_id=crawl.id, fetched_at=now, status_code=200, title=title,
                            headings_json=headings or {}))
        db.flush()
    return page


def observe(db, site, page, query, *, days_ago, impressions, clicks=0, position=8.0, country="US", device="MOBILE"):
    db.add(KeywordObservation(website_id=site.id, page_id=page.id if page else None, query=query, date=date.today() - timedelta(days=days_ago),
                              clicks=clicks, impressions=impressions, ctr=clicks / impressions if impressions else 0.0,
                              average_position=position, country=country, device=device, source="google_search_console"))
    db.flush()
