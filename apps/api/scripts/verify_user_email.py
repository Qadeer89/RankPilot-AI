"""Mark a user's email address as verified, from the server.

    .venv/bin/python scripts/verify_user_email.py --email you@example.com

For the server operator only (it needs database access). The normal route is the emailed link
(POST /auth/send-verification-email); use this when outgoing email is not configured yet.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.session import SessionLocal  # noqa: E402
from app.models.audit_event import AuditEvent  # noqa: E402
from app.models.user import User  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--email", required=True)
    args = ap.parse_args()
    db = SessionLocal()
    user = db.query(User).filter(User.email == args.email.strip().lower()).one_or_none()
    if user is None:
        print("No such user.")
        return 1
    if user.email_verified_at is not None:
        print(f"{user.email} is already verified ({user.email_verified_at:%Y-%m-%d %H:%M} UTC).")
        return 0
    user.email_verified_at = datetime.now(timezone.utc)
    db.add(AuditEvent(organization_id=None, actor_user_id=None, action="user.email_verified_by_operator",
                      resource_type="user", resource_id=str(user.id), metadata_json={"via": "scripts/verify_user_email.py"}))
    db.commit()
    print(f"Verified {user.email}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
