"""Encrypted storage and refresh of Google OAuth tokens
(RP-0501, SECURITY_SPECIFICATION.md #3: "Encrypt OAuth/connector tokens at
rest ... rotate/revoke on disconnect").
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import httpx
from sqlalchemy.orm import Session

from app.core.encryption import decrypt_text, encrypt_text
from app.integrations.google_search_console import TokenSet, refresh_access_token
from app.models.oauth_connection import OAuthConnection, OAuthConnectionStatus, OAuthProvider


def _serialize(token_set: TokenSet) -> str:
    return encrypt_text(
        json.dumps(
            {
                "access_token": token_set.access_token,
                "refresh_token": token_set.refresh_token,
                "token_type": token_set.token_type,
                "scope": token_set.scope,
            }
        )
    )


def _deserialize(encrypted: str) -> dict:
    return json.loads(decrypt_text(encrypted))


def upsert_connection(db: Session, organization_id: uuid.UUID, token_set: TokenSet) -> OAuthConnection:
    connection = (
        db.query(OAuthConnection)
        .filter(
            OAuthConnection.organization_id == organization_id,
            OAuthConnection.provider == OAuthProvider.google_search_console,
        )
        .one_or_none()
    )
    if connection is None:
        connection = OAuthConnection(
            organization_id=organization_id,
            provider=OAuthProvider.google_search_console,
            encrypted_token_reference=_serialize(token_set),
            scopes=[token_set.scope],
            status=OAuthConnectionStatus.connected,
            expires_at=token_set.expires_at,
        )
        db.add(connection)
    else:
        # A refresh_token is only returned on the *first* consent grant;
        # keep the previously stored one if Google didn't send a new one.
        if token_set.refresh_token is None:
            existing = _deserialize(connection.encrypted_token_reference)
            token_set = TokenSet(
                access_token=token_set.access_token,
                refresh_token=existing.get("refresh_token"),
                expires_at=token_set.expires_at,
                scope=token_set.scope,
                token_type=token_set.token_type,
            )
        connection.encrypted_token_reference = _serialize(token_set)
        connection.scopes = [token_set.scope]
        connection.status = OAuthConnectionStatus.connected
        connection.expires_at = token_set.expires_at
    db.flush()
    return connection


def get_valid_access_token(db: Session, organization_id: uuid.UUID) -> str:
    connection = (
        db.query(OAuthConnection)
        .filter(
            OAuthConnection.organization_id == organization_id,
            OAuthConnection.provider == OAuthProvider.google_search_console,
            OAuthConnection.status == OAuthConnectionStatus.connected,
        )
        .one_or_none()
    )
    if connection is None:
        raise LookupError("No connected Google Search Console account for this organization.")

    stored = _deserialize(connection.encrypted_token_reference)

    if connection.expires_at and connection.expires_at > datetime.now(timezone.utc):
        return stored["access_token"]

    if not stored.get("refresh_token"):
        connection.status = OAuthConnectionStatus.error
        db.flush()
        raise LookupError("Access token expired and no refresh token is available; reconnect required.")

    refreshed = refresh_access_token(stored["refresh_token"])
    connection.encrypted_token_reference = _serialize(refreshed)
    connection.expires_at = refreshed.expires_at
    db.flush()
    return refreshed.access_token


def disconnect(db: Session, organization_id: uuid.UUID) -> None:
    connection = (
        db.query(OAuthConnection)
        .filter(
            OAuthConnection.organization_id == organization_id,
            OAuthConnection.provider == OAuthProvider.google_search_console,
        )
        .one_or_none()
    )
    if connection is None:
        return

    stored = _deserialize(connection.encrypted_token_reference)
    try:
        httpx.post(
            "https://oauth2.googleapis.com/revoke",
            data={"token": stored["access_token"]},
            timeout=10.0,
        )
    except httpx.HTTPError:
        pass  # Best-effort revoke; local status change below is what matters.

    connection.status = OAuthConnectionStatus.disconnected
    db.flush()
