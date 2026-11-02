import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.integrations import token_store
from app.integrations.google_oauth_common import TokenSet
from app.integrations.google_search_console import refresh_access_token
from app.models.oauth_connection import OAuthConnection, OAuthConnectionStatus, OAuthProvider
from app.models.organization import Organization

PROVIDER = OAuthProvider.google_search_console


def _make_org(db_session):
    org = Organization(name="Token Store Org", slug=f"token-store-{uuid.uuid4().hex[:8]}")
    db_session.add(org)
    db_session.flush()
    return org


def test_upsert_connection_round_trips_and_encrypts(db_session):
    org = _make_org(db_session)
    token_set = TokenSet(
        access_token="access-1",
        refresh_token="refresh-1",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        scope="scope",
        token_type="Bearer",
    )
    connection = token_store.upsert_connection(db_session, org.id, PROVIDER, token_set)

    assert connection.encrypted_token_reference != "access-1"
    assert "access-1" not in connection.encrypted_token_reference

    access_token = token_store.get_valid_access_token(
        db_session, org.id, PROVIDER, refresh_fn=refresh_access_token
    )
    assert access_token == "access-1"


def test_upsert_connection_preserves_refresh_token_when_not_resent(db_session):
    org = _make_org(db_session)
    first = TokenSet(
        access_token="access-1",
        refresh_token="refresh-1",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        scope="scope",
        token_type="Bearer",
    )
    token_store.upsert_connection(db_session, org.id, PROVIDER, first)

    second = TokenSet(
        access_token="access-2",
        refresh_token=None,  # Google only returns this on first consent.
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        scope="scope",
        token_type="Bearer",
    )
    token_store.upsert_connection(db_session, org.id, PROVIDER, second)

    stored = token_store._deserialize(
        db_session.query(OAuthConnection).filter(OAuthConnection.organization_id == org.id).one().encrypted_token_reference
    )
    assert stored["refresh_token"] == "refresh-1"
    assert stored["access_token"] == "access-2"


def test_get_valid_access_token_refreshes_when_expired(db_session, monkeypatch):
    org = _make_org(db_session)
    expired = TokenSet(
        access_token="old-access",
        refresh_token="refresh-1",
        expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        scope="scope",
        token_type="Bearer",
    )
    token_store.upsert_connection(db_session, org.id, PROVIDER, expired)

    def fake_refresh(refresh_token):
        assert refresh_token == "refresh-1"
        return TokenSet(
            access_token="new-access",
            refresh_token=refresh_token,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            scope="scope",
            token_type="Bearer",
        )

    access_token = token_store.get_valid_access_token(db_session, org.id, PROVIDER, refresh_fn=fake_refresh)
    assert access_token == "new-access"


def test_get_valid_access_token_raises_when_not_connected(db_session):
    org = _make_org(db_session)
    with pytest.raises(LookupError):
        token_store.get_valid_access_token(db_session, org.id, PROVIDER, refresh_fn=refresh_access_token)


def test_disconnect_marks_status_disconnected(db_session, monkeypatch):
    org = _make_org(db_session)
    token_set = TokenSet(
        access_token="access-1",
        refresh_token="refresh-1",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        scope="scope",
        token_type="Bearer",
    )
    token_store.upsert_connection(db_session, org.id, PROVIDER, token_set)

    monkeypatch.setattr(token_store.httpx, "post", lambda *a, **k: None)
    token_store.disconnect(db_session, org.id, PROVIDER)

    connection = db_session.query(OAuthConnection).filter(OAuthConnection.organization_id == org.id).one()
    assert connection.status == OAuthConnectionStatus.disconnected

    with pytest.raises(LookupError):
        token_store.get_valid_access_token(db_session, org.id, PROVIDER, refresh_fn=refresh_access_token)
