"""Password reset flow (RP13-followup: the earlier security review
found no self-service password recovery path existed at all)."""

from datetime import datetime, timedelta, timezone

from app.core.verification import hash_token
from app.models.password_reset_token import PasswordResetToken
from app.models.user import User


def _register(client, email):
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "original-password-123", "organization_name": "Reset Org"},
    )
    assert response.status_code == 201
    return response.json()["access_token"]


def test_forgot_password_returns_generic_message_for_existing_account(client, db_session):
    _register(client, "reset-user@example.com")
    response = client.post("/api/v1/auth/forgot-password", json={"email": "reset-user@example.com"})
    assert response.status_code == 200
    assert "reset link has been sent" in response.json()["message"]


def test_forgot_password_returns_same_generic_message_for_unknown_account(client):
    # Must not leak whether an email is registered.
    response = client.post("/api/v1/auth/forgot-password", json={"email": "nobody-at-all@example.com"})
    assert response.status_code == 200
    assert "reset link has been sent" in response.json()["message"]


def test_forgot_password_creates_a_hashed_single_use_token(client, db_session):
    _register(client, "reset-token-check@example.com")
    client.post("/api/v1/auth/forgot-password", json={"email": "reset-token-check@example.com"})

    user = db_session.query(User).filter(User.email == "reset-token-check@example.com").one()
    tokens = db_session.query(PasswordResetToken).filter(PasswordResetToken.user_id == user.id).all()
    assert len(tokens) == 1
    assert tokens[0].used_at is None
    # The raw token is never stored -- only its hash.
    assert tokens[0].token_hash != ""
    assert len(tokens[0].token_hash) == 64  # sha256 hex digest


def test_reset_password_with_valid_token_succeeds_and_allows_new_login(client, db_session):
    _register(client, "reset-success@example.com")
    user = db_session.query(User).filter(User.email == "reset-success@example.com").one()

    raw_token = "a-known-raw-token-for-testing"
    db_session.add(
        PasswordResetToken(
            user_id=user.id,
            token_hash=hash_token(raw_token),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
        )
    )
    db_session.commit()

    response = client.post(
        "/api/v1/auth/reset-password", json={"token": raw_token, "new_password": "brand-new-password-456"}
    )
    assert response.status_code == 200

    old_login = client.post(
        "/api/v1/auth/login", json={"email": "reset-success@example.com", "password": "original-password-123"}
    )
    assert old_login.status_code == 401

    new_login = client.post(
        "/api/v1/auth/login", json={"email": "reset-success@example.com", "password": "brand-new-password-456"}
    )
    assert new_login.status_code == 200


def test_reset_password_token_is_single_use(client, db_session):
    _register(client, "reset-single-use@example.com")
    user = db_session.query(User).filter(User.email == "reset-single-use@example.com").one()

    raw_token = "single-use-token"
    db_session.add(
        PasswordResetToken(
            user_id=user.id,
            token_hash=hash_token(raw_token),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
        )
    )
    db_session.commit()

    first = client.post(
        "/api/v1/auth/reset-password", json={"token": raw_token, "new_password": "first-new-password-1"}
    )
    assert first.status_code == 200

    second = client.post(
        "/api/v1/auth/reset-password", json={"token": raw_token, "new_password": "second-new-password-2"}
    )
    assert second.status_code == 400


def test_reset_password_rejects_expired_token(client, db_session):
    _register(client, "reset-expired@example.com")
    user = db_session.query(User).filter(User.email == "reset-expired@example.com").one()

    raw_token = "an-expired-token"
    db_session.add(
        PasswordResetToken(
            user_id=user.id,
            token_hash=hash_token(raw_token),
            expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        )
    )
    db_session.commit()

    response = client.post(
        "/api/v1/auth/reset-password", json={"token": raw_token, "new_password": "does-not-matter-123"}
    )
    assert response.status_code == 400


def test_reset_password_rejects_unknown_token(client):
    response = client.post(
        "/api/v1/auth/reset-password", json={"token": "never-issued-token", "new_password": "does-not-matter-123"}
    )
    assert response.status_code == 400


def test_reset_password_invalidates_other_outstanding_tokens_for_the_same_user(client, db_session):
    _register(client, "reset-invalidate@example.com")
    user = db_session.query(User).filter(User.email == "reset-invalidate@example.com").one()

    token_a = "token-a-older"
    token_b = "token-b-newer"
    db_session.add_all(
        [
            PasswordResetToken(
                user_id=user.id, token_hash=hash_token(token_a), expires_at=datetime.now(timezone.utc) + timedelta(minutes=30)
            ),
            PasswordResetToken(
                user_id=user.id, token_hash=hash_token(token_b), expires_at=datetime.now(timezone.utc) + timedelta(minutes=30)
            ),
        ]
    )
    db_session.commit()

    used_b = client.post(
        "/api/v1/auth/reset-password", json={"token": token_b, "new_password": "newer-password-123"}
    )
    assert used_b.status_code == 200

    stale_a = client.post(
        "/api/v1/auth/reset-password", json={"token": token_a, "new_password": "older-password-456"}
    )
    assert stale_a.status_code == 400
