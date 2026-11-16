"""Plan (and optionally create tasks for) titles that show the brand twice.

    # 1. see what would change (read-only, nothing is created)
    .venv/bin/python scripts/repair_doubled_titles.py --email you@example.com --site gulsrehab --limit 10

    # 2. create approval-pending tasks for those pages
    .venv/bin/python scripts/repair_doubled_titles.py --email you@example.com --site gulsrehab --limit 10 --create

Tasks created this way never run by themselves: approve and execute each one
in the website's Tasks tab. No AI call is made.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.session import SessionLocal  # noqa: E402
from app.growth.title_repair import create_repair_tasks, plan_title_repairs  # noqa: E402
from app.models.audit_event import AuditEvent  # noqa: E402
from app.models.membership import Membership  # noqa: E402
from app.models.user import User  # noqa: E402
from app.models.website import Website  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--email", required=True)
    ap.add_argument("--site", required=True, help="part of the website's hostname")
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--create", action="store_true", help="create the approval-pending tasks (default: only show the plan)")
    args = ap.parse_args()

    db = SessionLocal()
    user = db.query(User).filter(User.email == args.email.lower()).one_or_none()
    if user is None:
        print("No such user.")
        return 1
    org_ids = [m.organization_id for m in db.query(Membership).filter(Membership.user_id == user.id)]
    sites = [w for w in db.query(Website).filter(Website.organization_id.in_(org_ids)).all()
             if args.site.lower() in w.hostname.lower()]
    if len(sites) != 1:
        print(f"Expected exactly one website matching '{args.site}', found {len(sites)}.")
        return 1
    site = sites[0]

    plan = plan_title_repairs(db, site, limit=args.limit)
    print(f"=== {site.display_name} ({site.hostname}) ===")
    if plan.reason_none:
        print(plan.reason_none)
        return 0
    print(f"{len(plan.candidates)} title(s) to fix in this batch; {plan.skipped_already_pending} already have a pending fix.")
    for c in plan.candidates:
        print(f"- {c.target_url}\n    live now : {c.live_title!r}\n    new value: {c.fixed_title!r}")

    if not args.create:
        print("\nNothing was created. Add --create to create approval-pending tasks.")
        return 0
    if not plan.candidates:
        return 0

    tasks = create_repair_tasks(db, site, plan.candidates, requested_by=user.id)
    db.add(AuditEvent(organization_id=site.organization_id, actor_user_id=user.id, action="title_repair.create_tasks",
                      resource_type="website", resource_id=str(site.id), metadata_json={"tasks": len(tasks)}))
    db.commit()
    print(f"\nCreated {len(tasks)} task(s), all waiting for your approval. Open the website's Tasks tab:")
    print("'Needs your approval' -> Approve -> Execute. Nothing changes on the live site before that.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
