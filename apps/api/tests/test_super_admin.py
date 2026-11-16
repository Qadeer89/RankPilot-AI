"""Super Admin security (spec section 9 / test group C): exactly one account, verified, enforced on the
server for every admin route, impossible to reach by forging anything the browser controls."""

import re
import uuid
from datetime import datetime, timedelta, timezone

import jwt
import pytest

from app.admin.audit import record_admin_action
from app.config import get_settings
from app.core.admin import is_super_admin, super_admin_state
from app.core.security import create_access_token
from app.core.verification import hash_token
from app.main import app
from app.models.audit_event import AuditEvent
from app.models.email_verification_token import EmailVerificationToken
from app.models.user import User, UserStatus
from app.notifications import email as email_module

ADMIN = "qaqadeer@gmail.com"


def _register(client, email, **extra):
    r = client.post("/api/v1/auth/register", json={"email": email, "password": "correct-horse-battery",
                                                    "organization_name": f"Org {email}", **extra})
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _verify(db_session, email):
    user = db_session.query(User).filter(User.email == email).one()
    user.email_verified_at = datetime.now(timezone.utc)
    db_session.commit()
    return user


@pytest.fixture
def mailbox(monkeypatch):
    sent = []
    import app.api.v1.endpoints.auth as auth_endpoint
    monkeypatch.setattr(auth_endpoint, "send_plain_email", lambda to, subject, body: sent.append((to, subject, body)))
    return sent


# --- who may get in ---------------------------------------------------------------------------

def test_the_verified_configured_account_is_the_super_admin(client, db_session):
    headers = _register(client, ADMIN)
    _verify(db_session, ADMIN)
    assert client.get("/api/v1/admin/whoami", headers=headers).json() == {
        "id": client.get("/api/v1/me", headers=headers).json()["user"]["id"], "email": ADMIN, "is_super_admin": True}
    me = client.get("/api/v1/me", headers=headers).json()["user"]
    assert (me["is_super_admin"], me["email_verified"]) == (True, True)


def test_email_matching_is_case_insensitive(client, db_session):
    # a mixed-case address as it might be stored by another route: still the same mailbox
    user = User(email="QAQadeer@Gmail.com", hashed_password="x", email_verified_at=datetime.now(timezone.utc))
    db_session.add(user)
    db_session.commit()
    headers = {"Authorization": f"Bearer {create_access_token(user.id)}"}
    assert client.get("/api/v1/admin/whoami", headers=headers).status_code == 200
    assert is_super_admin(user) is True


def test_an_ordinary_user_is_denied(client):
    headers = _register(client, "someone@example.com")
    r = client.get("/api/v1/admin/whoami", headers=headers)
    assert r.status_code == 403
    me = client.get("/api/v1/me", headers=headers).json()["user"]
    assert (me["is_super_admin"], me["is_platform_admin"]) == (False, False)


def test_the_admin_address_without_a_verified_email_is_denied_with_a_clear_reason(client):
    headers = _register(client, ADMIN)  # anyone could register this address; owning the mailbox is what counts
    r = client.get("/api/v1/admin/whoami", headers=headers)
    assert r.status_code == 403 and r.json()["detail"]["code"] == "email_not_verified"
    assert client.get("/api/v1/me", headers=headers).json()["user"]["is_super_admin"] is False


@pytest.mark.parametrize("lookalike", ["qaqadeer@gmail.com.evil.example", "qaqadeer+admin@gmail.com", "xqaqadeer@gmail.com",
                                       "qaqadeer@gmail.co", "qa.qadeer@gmail.com"])
def test_lookalike_addresses_are_never_admin_even_when_verified(client, db_session, lookalike):
    headers = _register(client, lookalike)
    _verify(db_session, lookalike)
    assert client.get("/api/v1/admin/whoami", headers=headers).status_code == 403


def test_a_suspended_admin_account_is_locked_out_everywhere(client, db_session):
    headers = _register(client, ADMIN)
    user = _verify(db_session, ADMIN)
    user.status = UserStatus.disabled
    db_session.commit()
    assert client.get("/api/v1/admin/whoami", headers=headers).status_code == 403
    assert client.get("/api/v1/me", headers=headers).status_code == 403  # the existing token stops working at once
    login = client.post("/api/v1/auth/login", json={"email": ADMIN, "password": "correct-horse-battery"})
    assert login.status_code == 403
    assert super_admin_state(user) == "suspended"


def test_unauthenticated_and_garbage_tokens_are_refused(client):
    assert client.get("/api/v1/admin/whoami").status_code == 401
    assert client.get("/api/v1/admin/whoami", headers={"Authorization": "Bearer nonsense"}).status_code == 401


# --- forging what the browser controls --------------------------------------------------------

def test_headers_query_strings_and_body_flags_cannot_grant_admin(client):
    headers = _register(client, "forger@example.com", is_super_admin=True, is_platform_admin=True, role="admin")
    spoof = {**headers, "X-Role": "super_admin", "X-Admin": "true", "X-User-Email": ADMIN, "X-Forwarded-User": ADMIN}
    assert client.get("/api/v1/admin/whoami", headers=spoof, params={"is_super_admin": "true", "role": "admin"}).status_code == 403


def test_a_validly_signed_token_with_extra_claims_is_still_just_that_user(client, db_session):
    headers = _register(client, "claims@example.com")
    user = db_session.query(User).filter(User.email == "claims@example.com").one()
    settings = get_settings()
    forged = jwt.encode(
        {"sub": str(user.id), "exp": datetime.now(timezone.utc) + timedelta(hours=1), "is_super_admin": True, "role": "super_admin",
         "email": ADMIN}, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    assert client.get("/api/v1/admin/whoami", headers={"Authorization": f"Bearer {forged}"}).status_code == 403


def test_a_token_signed_with_a_different_secret_is_rejected(client, db_session):
    _register(client, ADMIN)
    user = _verify(db_session, ADMIN)
    forged = jwt.encode({"sub": str(user.id), "exp": datetime.now(timezone.utc) + timedelta(hours=1)}, "not-the-secret", algorithm="HS256")
    assert client.get("/api/v1/admin/whoami", headers={"Authorization": f"Bearer {forged}"}).status_code == 401


def test_no_endpoint_lets_a_user_change_their_own_privileges(client):
    paths = {r.path for r in app.routes if hasattr(r, "path")}
    risky = [p for p in paths if re.search(r"(role|privilege|promote|is_platform_admin|make-admin)", p) and "/organizations/" not in p]
    assert risky == []


def test_registering_the_admin_address_twice_is_refused(client):
    _register(client, ADMIN)
    r = client.post("/api/v1/auth/register", json={"email": ADMIN, "password": "correct-horse-battery", "organization_name": "Again"})
    assert r.status_code in (400, 409)


# --- every admin route is gated ---------------------------------------------------------------

def _admin_routes():
    for route in app.routes:
        path = getattr(route, "path", "")
        if path.startswith("/api/v1/admin"):
            for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
                yield method, path


def test_there_are_admin_routes_to_check():
    routes = list(_admin_routes())
    assert len(routes) >= 5 and any(p.startswith("/api/v1/admin/knowledge") for _, p in routes)


def _fill(path):
    return re.sub(r"\{[^}]+\}", str(uuid.uuid4()), path)


def test_every_admin_route_refuses_anonymous_and_ordinary_users(client):
    ordinary = _register(client, "ordinary@example.com")
    for method, path in _admin_routes():
        url = _fill(path)
        anonymous = client.request(method, url, json={} if method in ("POST", "PUT", "PATCH") else None)
        assert anonymous.status_code == 401, f"{method} {path} is reachable without logging in ({anonymous.status_code})"
        normal = client.request(method, url, headers=ordinary, json={} if method in ("POST", "PUT", "PATCH") else None)
        assert normal.status_code == 403, f"{method} {path} is reachable by an ordinary user ({normal.status_code})"


def test_every_admin_route_refuses_the_admin_address_until_its_email_is_verified(client):
    unverified = _register(client, ADMIN)
    for method, path in _admin_routes():
        r = client.request(method, _fill(path), headers=unverified, json={} if method in ("POST", "PUT", "PATCH") else None)
        assert r.status_code == 403, f"{method} {path} let an unverified admin address in ({r.status_code})"


def test_there_is_no_route_that_edits_or_deletes_audit_history():
    for method, path in _admin_routes():
        if "audit" in path:
            assert method == "GET", f"{method} {path} could change audit history"


# --- email verification -----------------------------------------------------------------------

def _token_from(mailbox):
    return re.search(r"token=([\w-]+)", mailbox[-1][2]).group(1)


def test_verifying_by_email_unlocks_the_admin_account(client, db_session, mailbox):
    headers = _register(client, ADMIN)
    assert client.get("/api/v1/admin/whoami", headers=headers).status_code == 403

    assert client.post("/api/v1/auth/send-verification-email", headers=headers).status_code == 200
    assert mailbox[-1][0] == ADMIN and "/verify-email?token=" in mailbox[-1][2]
    token = _token_from(mailbox)

    assert client.post("/api/v1/auth/verify-email", json={"token": token}).status_code == 200
    assert client.get("/api/v1/admin/whoami", headers=headers).status_code == 200
    assert db_session.query(AuditEvent).filter(AuditEvent.action == "user.email_verified").count() == 1


def test_a_verification_link_works_once_only(client, mailbox):
    headers = _register(client, "once@example.com")
    client.post("/api/v1/auth/send-verification-email", headers=headers)
    token = _token_from(mailbox)
    assert client.post("/api/v1/auth/verify-email", json={"token": token}).status_code == 200
    assert client.post("/api/v1/auth/verify-email", json={"token": token}).status_code == 400


def test_an_expired_or_unknown_verification_link_is_refused(client, db_session, mailbox):
    headers = _register(client, "late@example.com")
    client.post("/api/v1/auth/send-verification-email", headers=headers)
    token = _token_from(mailbox)
    db_session.query(EmailVerificationToken).update({"expires_at": datetime.now(timezone.utc) - timedelta(minutes=1)})
    db_session.commit()
    assert client.post("/api/v1/auth/verify-email", json={"token": token}).status_code == 400
    assert client.post("/api/v1/auth/verify-email", json={"token": "never-issued"}).status_code == 400
    assert db_session.query(User).filter(User.email == "late@example.com").one().email_verified_at is None


def test_a_link_sent_to_an_old_address_verifies_nothing_after_the_email_changes(client, db_session, mailbox):
    headers = _register(client, "before@example.com")
    client.post("/api/v1/auth/send-verification-email", headers=headers)
    token = _token_from(mailbox)
    db_session.query(User).filter(User.email == "before@example.com").one().email = ADMIN  # address taken over / changed
    db_session.commit()
    assert client.post("/api/v1/auth/verify-email", json={"token": token}).status_code == 400
    assert client.get("/api/v1/admin/whoami", headers=headers).status_code == 403


def test_sending_a_verification_email_needs_a_login_and_is_idempotent_once_verified(client, db_session, mailbox):
    assert client.post("/api/v1/auth/send-verification-email").status_code == 401
    headers = _register(client, "done@example.com")
    _verify(db_session, "done@example.com")
    r = client.post("/api/v1/auth/send-verification-email", headers=headers)
    assert r.status_code == 200 and "already verified" in r.json()["message"] and mailbox == []


def test_only_the_token_hash_is_stored(client, db_session, mailbox):
    headers = _register(client, "hash@example.com")
    client.post("/api/v1/auth/send-verification-email", headers=headers)
    token = _token_from(mailbox)
    row = db_session.query(EmailVerificationToken).one()
    assert row.token_hash == hash_token(token) and token not in row.token_hash


# --- audit + operator script ------------------------------------------------------------------

def test_admin_actions_are_audited_with_who_what_why_and_before_after(db_session):
    admin = User(email=ADMIN, hashed_password="x", email_verified_at=datetime.now(timezone.utc))
    db_session.add(admin)
    db_session.flush()
    record_admin_action(db_session, admin, action="user.suspend", resource_type="user", resource_id="u-1",
                        reason="Chargeback abuse", before={"status": "active"}, after={"status": "disabled"})
    event = db_session.query(AuditEvent).filter(AuditEvent.action == "admin.user.suspend").one()
    assert event.actor_user_id == admin.id and event.resource_id == "u-1" and event.created_at is not None
    assert event.metadata_json == {"reason": "Chargeback abuse", "before": {"status": "active"}, "after": {"status": "disabled"}}


def test_the_operator_script_verifies_an_account_and_records_it(db_session, monkeypatch):
    import importlib.util
    import pathlib

    spec = importlib.util.spec_from_file_location("verify_user_email", pathlib.Path(__file__).parent.parent / "scripts" / "verify_user_email.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    user = User(email=ADMIN, hashed_password="x")
    db_session.add(user)
    db_session.flush()
    monkeypatch.setattr(module, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(db_session, "close", lambda: None, raising=False)
    monkeypatch.setattr("sys.argv", ["verify_user_email.py", "--email", ADMIN])

    assert module.main() == 0
    assert is_super_admin(user) is True
    assert db_session.query(AuditEvent).filter(AuditEvent.action == "user.email_verified_by_operator").count() == 1
    assert module.main() == 0  # running it again changes nothing
