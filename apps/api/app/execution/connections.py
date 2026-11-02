"""Encrypted storage and retrieval of WordPress connector credentials
(RP-0703, SECURITY_SPECIFICATION.md #3).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.connectors.wordpress import WordPressConnectorError, WordPressCredentials, verify_credentials
from app.core.encryption import decrypt_text, encrypt_text
from app.models.website import Website
from app.models.website_connection import ConnectorType, WebsiteConnection, WebsiteConnectionStatus


def connect_wordpress(
    db: Session, website: Website, username: str, application_password: str
) -> WebsiteConnection:
    """Verify the credentials against the live site before storing them —
    never persist a connector credential that hasn't been confirmed to
    work (WEBSITE_CONNECTORS.md #3: "Verify site identity and connector
    permissions").
    """
    candidate = WordPressCredentials(
        site_url=website.canonical_url, username=username, application_password=application_password
    )
    try:
        verify_credentials(candidate)
    except WordPressConnectorError as exc:
        raise ValueError(f"Could not verify WordPress credentials: {exc}") from exc

    encrypted = encrypt_text(json.dumps({"username": username, "application_password": application_password}))

    connection = (
        db.query(WebsiteConnection)
        .filter(WebsiteConnection.website_id == website.id, WebsiteConnection.connector_type == ConnectorType.wordpress)
        .one_or_none()
    )
    now = datetime.now(timezone.utc)
    if connection is None:
        connection = WebsiteConnection(
            website_id=website.id,
            connector_type=ConnectorType.wordpress,
            encrypted_secret_reference=encrypted,
            granted_scopes=["read", "edit_posts"],
            status=WebsiteConnectionStatus.connected,
            last_verified_at=now,
        )
        db.add(connection)
    else:
        connection.encrypted_secret_reference = encrypted
        connection.status = WebsiteConnectionStatus.connected
        connection.last_verified_at = now
    db.flush()
    return connection


def get_wordpress_credentials(db: Session, website: Website) -> WordPressCredentials:
    connection = (
        db.query(WebsiteConnection)
        .filter(
            WebsiteConnection.website_id == website.id,
            WebsiteConnection.connector_type == ConnectorType.wordpress,
            WebsiteConnection.status == WebsiteConnectionStatus.connected,
        )
        .one_or_none()
    )
    if connection is None:
        raise LookupError("No connected WordPress connector for this website.")

    stored = json.loads(decrypt_text(connection.encrypted_secret_reference))
    return WordPressCredentials(
        site_url=website.canonical_url,
        username=stored["username"],
        application_password=stored["application_password"],
    )


def disconnect_wordpress(db: Session, website: Website) -> None:
    connection = (
        db.query(WebsiteConnection)
        .filter(WebsiteConnection.website_id == website.id, WebsiteConnection.connector_type == ConnectorType.wordpress)
        .one_or_none()
    )
    if connection is None:
        return
    connection.status = WebsiteConnectionStatus.disconnected
    db.flush()
