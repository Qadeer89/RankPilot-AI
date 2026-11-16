"""Do the changes RankPilot applied actually show on the public page?

    .venv/bin/python scripts/check_applied_changes.py --email you@example.com [--site leadflowstudiohq]

For every completed set_title / set_meta_description task it re-fetches the
public page (the same safe, robots-aware fetcher the crawler uses) and
compares what a crawler sees with the value RankPilot applied. Read-only:
it never writes to a CMS or to RankPilot's own tables.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.crawler.extract import extract_page  # noqa: E402
from app.crawler.fetch import FetchError, safe_fetch  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.growth.recrawl import RECRAWL_FIELDS, applied_value  # noqa: E402
from app.models.change_record import ChangeRecord  # noqa: E402
from app.models.membership import Membership  # noqa: E402
from app.models.rollback_record import RollbackRecord, RollbackStatus  # noqa: E402
from app.models.seo_opportunity import SEOOpportunity  # noqa: E402
from app.models.seo_task import SEOTask, SEOTaskStatus  # noqa: E402
from app.models.user import User  # noqa: E402
from app.models.website import Website  # noqa: E402
from app.seo_rules.site_title import site_title_suffix  # noqa: E402
from app.seo_rules.title_template import has_duplicate_brand, strip_title_suffix, title_matches  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--email", required=True)
    ap.add_argument("--site", help="only websites whose hostname contains this text")
    args = ap.parse_args()

    db = SessionLocal()
    user = db.query(User).filter(User.email == args.email.lower()).one_or_none()
    if user is None:
        print("No such user.")
        return 1
    org_ids = [m.organization_id for m in db.query(Membership).filter(Membership.user_id == user.id)]
    sites = [w for w in db.query(Website).filter(Website.organization_id.in_(org_ids)).all()
             if not args.site or args.site.lower() in w.hostname.lower()]

    for site in sites:
        print(f"\n=== {site.display_name} ({site.hostname}) | automation mode: {site.automation_mode.value} ===")
        rows = (
            db.query(SEOTask, ChangeRecord)
            .join(ChangeRecord, ChangeRecord.seo_task_id == SEOTask.id)
            .filter(SEOTask.website_id == site.id, SEOTask.status == SEOTaskStatus.completed,
                    SEOTask.task_type.in_(list(RECRAWL_FIELDS)))
            .order_by(ChangeRecord.executed_at.desc())
            .all()
        )
        if not rows:
            print("no completed title/meta changes")
            continue
        suffix = site_title_suffix(db, site)
        print(f"site title template (learned from crawled titles): {suffix.joined if suffix else 'none detected'}")
        # newest change per (url, operation)
        seen: set[tuple[str, str]] = set()
        matched = mismatched = errors = duplicated = 0
        for task, change in rows:
            url = task.proposed_change_json.get("target_url")
            key = (url, task.task_type)
            if not url or key in seen:
                continue
            seen.add(key)
            rolled_back = (
                db.query(RollbackRecord)
                .filter(RollbackRecord.change_record_id == change.id, RollbackRecord.status == RollbackStatus.completed)
                .first() is not None
            )
            if rolled_back:
                print(f"- {task.task_type} {url}: rolled back, skipped")
                continue
            expected = applied_value(change, task)
            opp = db.get(SEOOpportunity, task.opportunity_id) if task.opportunity_id else None
            opp_state = opp.status.value if opp else "-"
            try:
                fetched = safe_fetch(url)
                found = getattr(extract_page(fetched.body, base_url=fetched.final_url, site_hostname=site.hostname),
                                RECRAWL_FIELDS[task.task_type])
            except FetchError as exc:
                errors += 1
                print(f"- {task.task_type} {url}: could not fetch the page ({exc})")
                continue
            is_title = task.task_type == "set_title"
            ok = title_matches(expected, found) if is_title else (found or "").strip() == (expected or "").strip()
            duplicate = is_title and has_duplicate_brand(found)
            matched += ok
            mismatched += not ok
            duplicated += duplicate
            verdict = "MATCH" if ok else "DIFFERENT"
            if ok and found != expected:
                verdict += " (the site's title template adds text after it)"
            if duplicate:
                verdict += "  !! BRAND SHOWN TWICE"
            print(f"- {task.task_type} {url} [{change.connector_type.value}, applied {change.executed_at:%Y-%m-%d %H:%M}, opportunity: {opp_state}]")
            print(f"    applied : {expected!r}")
            print(f"    live now: {found!r}  -> {verdict}")
            if duplicate:
                print(f"    suggested page title without the repeated brand: {strip_title_suffix(expected or '', suffix)!r}")
        print(f"summary: {matched} match, {mismatched} different, {errors} not fetched, {duplicated} with the brand shown twice")
    return 0


if __name__ == "__main__":
    sys.exit(main())
