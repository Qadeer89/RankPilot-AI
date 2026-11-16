"""Who is the Super Admin. One configured account, and only while its email is verified and the account
is active. Everything is decided on the server from the database row: no role or flag sent by a browser
is ever consulted."""

from __future__ import annotations

from app.config import get_settings
from app.models.user import User, UserStatus


def configured_super_admin_email() -> str:
    return (get_settings().super_admin_email or "").strip().lower()


def super_admin_state(user: User) -> str:
    """"ok", or why not: "not_admin", "email_not_verified" or "suspended"."""
    configured = configured_super_admin_email()
    if not configured or (user.email or "").strip().lower() != configured:
        return "not_admin"
    if user.status != UserStatus.active:
        return "suspended"
    if user.email_verified_at is None:
        return "email_not_verified"
    return "ok"


def is_super_admin(user: User) -> bool:
    return super_admin_state(user) == "ok"
