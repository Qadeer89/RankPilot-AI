"""A revoked/expired Google refresh token (`invalid_grant`) is a permanent
failure: it says so, and the connection stops being used until reconnected."""

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.integrations import google_oauth_common, token_store
from app.integrations.google_oauth_common import GoogleApiError, GoogleReauthRequired, TokenSet
from app.models.oauth_connection import OAuthConnection, OAuthConnectionStatus, OAuthProvider
from app.models.organization import Organization


def _response(status, payload=None, text="boom"):
    def json_():
        if payload is None:
            raise ValueError("not json")
        return payload

    return SimpleNamespace(status_code=status, json=json_, text=text)


@pytest.fixture(autouse=True)
def _client_settings(monkeypatch):
    monkeypatch.setattr(google_oauth_common, "require_google_client_settings",
                        lambda: SimpleNamespace(google_client_id="id", google_client_secret="secret"))


def test_invalid_grant_is_reported_as_reauth_required(monkeypatch):
    monkeypatch.setattr(google_oauth_common.httpx, "post",
                        lambda *a, **k: _response(400, {"error": "invalid_grant", "error_description": "Token has been expired or revoked."}))
    with pytest.raises(GoogleReauthRequired) as exc:
        google_oauth_common.refresh_access_token("r", default_scope="s")
    assert "Reconnect" in str(exc.value)
    assert isinstance(exc.value, GoogleApiError)  # existing handlers still catch it


@pytest.mark.parametrize("response", [_response(500, None, "oops"), _response(400, {"error": "invalid_client"})])
def test_other_refresh_failures_stay_ordinary_errors(monkeypatch, response):
    monkeypatch.setattr(google_oauth_common.httpx, "post", lambda *a, **k: response)
    with pytest.raises(GoogleApiError) as exc:
        google_oauth_common.refresh_access_token("r", default_scope="s")
    assert not isinstance(exc.value, GoogleReauthRequired)


def _expired_connection(db_session):
    org = Organization(name="Reauth Org", slug=f"reauth-{uuid.uuid4().hex[:8]}")
    db_session.add(org)
    db_session.flush()
    token_store.upsert_connection(
        db_session, org.id, OAuthProvider.google_analytics,
        TokenSet(access_token="a", refresh_token="r", expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
                 scope="s", token_type="Bearer"),
    )
    db_session.commit()
    return org


def test_a_revoked_token_marks_the_connection_as_needing_reconnect(db_session):
    org = _expired_connection(db_session)

    def refresh(_token):
        raise GoogleReauthRequired("revoked")

    with pytest.raises(GoogleReauthRequired):
        token_store.get_valid_access_token(db_session, org.id, OAuthProvider.google_analytics, refresh_fn=refresh)

    db_session.rollback()  # callers roll back on the exception; the status flip must survive
    connection = db_session.query(OAuthConnection).filter(OAuthConnection.organization_id == org.id).one()
    assert connection.status == OAuthConnectionStatus.error

    # subsequent syncs stop immediately instead of calling Google with a dead token
    with pytest.raises(LookupError):
        token_store.get_valid_access_token(db_session, org.id, OAuthProvider.google_analytics,
                                           refresh_fn=lambda t: pytest.fail("must not call Google again"))


def test_a_transient_refresh_failure_does_not_disconnect(db_session):
    org = _expired_connection(db_session)

    def refresh(_token):
        raise GoogleApiError("HTTP 503")

    with pytest.raises(GoogleApiError):
        token_store.get_valid_access_token(db_session, org.id, OAuthProvider.google_analytics, refresh_fn=refresh)
    db_session.rollback()
    connection = db_session.query(OAuthConnection).filter(OAuthConnection.organization_id == org.id).one()
    assert connection.status == OAuthConnectionStatus.connected


def test_reconnecting_restores_the_connection(db_session):
    org = _expired_connection(db_session)
    connection = db_session.query(OAuthConnection).filter(OAuthConnection.organization_id == org.id).one()
    connection.status = OAuthConnectionStatus.error
    db_session.commit()

    token_store.upsert_connection(
        db_session, org.id, OAuthProvider.google_analytics,
        TokenSet(access_token="new", refresh_token="r2", expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
                 scope="s", token_type="Bearer"),
    )
    assert token_store.get_valid_access_token(db_session, org.id, OAuthProvider.google_analytics,
                                              refresh_fn=lambda t: pytest.fail("fresh token")) == "new"
