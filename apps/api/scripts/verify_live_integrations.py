"""Read-only check of the real GSC / GA4 / CMS wiring for one account.

    .venv/bin/python scripts/verify_live_integrations.py --email you@example.com

Runs the normal Search Console and GA4 syncs for each of the account's
websites (these only write RankPilot's own tables), then prints what came
back. It never writes to a CMS.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.session import SessionLocal  # noqa: E402
from app.growth.lifecycle import execution_support  # noqa: E402
from app.integrations import ga4_sync, search_console_sync  # noqa: E402
from app.models.ga4_landing_page_metric import Ga4LandingPageMetric  # noqa: E402
from app.models.growth_recommendation import GrowthRecommendation  # noqa: E402
from app.models.keyword_observation import KeywordObservation  # noqa: E402
from app.models.membership import Membership  # noqa: E402
from app.models.user import User  # noqa: E402
from app.models.website import Website  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--email", required=True)
    args = ap.parse_args()
    db = SessionLocal()
    user = db.query(User).filter(User.email == args.email.lower()).one_or_none()
    if user is None:
        print("No such user.")
        return 1
    org_ids = [m.organization_id for m in db.query(Membership).filter(Membership.user_id == user.id)]
    sites = db.query(Website).filter(Website.organization_id.in_(org_ids)).all()
    for site in sites:
        print(f"\n=== {site.display_name} ({site.hostname}) ===")
        print(f"target: {site.target_country} + {site.additional_target_countries}, languages: {site.target_languages_by_country}")
        print(f"GSC property: {site.search_console_site_url or '-'} | GA4 property: {site.ga4_property_id or '-'}")
        if site.search_console_site_url:
            try:
                n = search_console_sync.sync_search_performance(db, site)
                db.commit()
                counts = Counter(c for (c,) in db.query(KeywordObservation.country).filter(KeywordObservation.website_id == site.id))
                bad = [c for c in counts if c is not None and not (len(c) == 2 and c.isupper())]
                print(f"GSC sync: {n} rows. countries stored: {dict(counts.most_common(8))}")
                print("GSC country format:", "OK (all ISO alpha-2)" if not bad else f"PROBLEM, not alpha-2: {bad[:5]}")
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                print(f"GSC sync FAILED: {type(exc).__name__}: {exc}")
        if site.ga4_property_id:
            try:
                n = ga4_sync.sync_ga4_landing_pages(db, site)
                db.commit()
                rows = db.query(Ga4LandingPageMetric).filter(Ga4LandingPageMetric.website_id == site.id).all()
                mapped = sum(1 for r in rows if r.page_id)
                print(f"GA4 landing sync: {n} path/day groups; stored rows {len(rows)}, mapped to crawled pages {mapped}")
                for r in sorted(rows, key=lambda r: -r.sessions)[:3]:
                    print(f"   {r.landing_page}: {r.sessions} sessions, mapped={bool(r.page_id)}")
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                print(f"GA4 landing sync FAILED: {type(exc).__name__}: {exc}")
        recs = db.query(GrowthRecommendation).filter(GrowthRecommendation.website_id == site.id).all()
        checked = [(rec, *execution_support(db, site, rec)) for rec in recs]
        executable = [(rec, reason) for rec, ok, reason in checked if ok]
        print(f"growth recommendations: {len(recs)} total, {len(executable)} can be applied through the connected CMS")
        for rec, _ in executable[:10]:
            print(f"   [{rec.status.value}] CAN apply via CMS: {rec.title[:70]}")
        by_reason: dict[str, int] = {}
        for _rec, ok, reason in checked:
            if not ok:
                by_reason[str(reason)] = by_reason.get(str(reason), 0) + 1
        for reason, count in sorted(by_reason.items(), key=lambda kv: -kv[1]):
            print(f"   {count} x cannot apply: {reason}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
