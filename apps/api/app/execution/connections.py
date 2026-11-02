"""Encrypted storage and retrieval of connector credentials for all
connector types (RP-0703, SECURITY_SPECIFICATION.md #3).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.connectors import github_pr, shopify, webflow
from app.connectors.errors import ConnectorError
from app.connectors.github_pr import GitHubCredentials
from app.connectors.shopify import ShopifyCredentials
from app.connectors.webflow import WebflowCredentials
from app.connectors.wordpress import WordPressConnectorError, WordPressCredentials, verify_credentials
from app.core.encryption import decrypt_text, encrypt_text
from app.models.website import Website
from app.models.website_connection import ConnectorType, WebsiteConnection, WebsiteConnectionStatus

# Order in which to prefer a connected connector when a website somehow has
# more than one live-write connector connected at once (shouldn't normally
# happen -- a site is usually WordPress, Shopify, Webflow, or custom-code).
CONTENT_CONNECTOR_PRIORITY = (
    ConnectorType.wordpress,
    ConnectorType.shopify,
    ConnectorType.webflow,
    ConnectorType.github,
)


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


def _upsert_connection(
    db: Session,
    website: Website,
    connector_type: ConnectorType,
    *,
    encrypted_secret: str,
    config: dict,
    granted_scopes: list[str],
) -> WebsiteConnection:
    connection = (
        db.query(WebsiteConnection)
        .filter(WebsiteConnection.website_id == website.id, WebsiteConnection.connector_type == connector_type)
        .one_or_none()
    )
    now = datetime.now(timezone.utc)
    if connection is None:
        connection = WebsiteConnection(
            website_id=website.id,
            connector_type=connector_type,
            encrypted_secret_reference=encrypted_secret,
            config_json=config,
            granted_scopes=granted_scopes,
            status=WebsiteConnectionStatus.connected,
            last_verified_at=now,
        )
        db.add(connection)
    else:
        connection.encrypted_secret_reference = encrypted_secret
        connection.config_json = config
        connection.status = WebsiteConnectionStatus.connected
        connection.last_verified_at = now
    db.flush()
    return connection


def _get_connection_or_raise(db: Session, website: Website, connector_type: ConnectorType) -> WebsiteConnection:
    connection = (
        db.query(WebsiteConnection)
        .filter(
            WebsiteConnection.website_id == website.id,
            WebsiteConnection.connector_type == connector_type,
            WebsiteConnection.status == WebsiteConnectionStatus.connected,
        )
        .one_or_none()
    )
    if connection is None:
        raise LookupError(f"No connected {connector_type.value} connector for this website.")
    return connection


def _disconnect(db: Session, website: Website, connector_type: ConnectorType) -> None:
    connection = (
        db.query(WebsiteConnection)
        .filter(WebsiteConnection.website_id == website.id, WebsiteConnection.connector_type == connector_type)
        .one_or_none()
    )
    if connection is None:
        return
    connection.status = WebsiteConnectionStatus.disconnected
    db.flush()


def connect_shopify(db: Session, website: Website, shop_domain: str, access_token: str) -> WebsiteConnection:
    candidate = ShopifyCredentials(shop_domain=shop_domain, access_token=access_token)
    try:
        shopify.verify_credentials(candidate)
    except ConnectorError as exc:
        raise ValueError(f"Could not verify Shopify credentials: {exc}") from exc

    encrypted = encrypt_text(json.dumps({"access_token": access_token}))
    return _upsert_connection(
        db,
        website,
        ConnectorType.shopify,
        encrypted_secret=encrypted,
        config={"shop_domain": shop_domain},
        # RP13-016: find_target searches both pages and products
        # (RESOURCE_TYPES_TO_SEARCH), so both resource types' scopes are
        # needed -- write_content alone doesn't cover product metafields.
        granted_scopes=["read_content", "write_content", "read_products", "write_products"],
    )


def get_shopify_credentials(db: Session, website: Website) -> ShopifyCredentials:
    connection = _get_connection_or_raise(db, website, ConnectorType.shopify)
    stored = json.loads(decrypt_text(connection.encrypted_secret_reference))
    return ShopifyCredentials(shop_domain=connection.config_json["shop_domain"], access_token=stored["access_token"])


def disconnect_shopify(db: Session, website: Website) -> None:
    _disconnect(db, website, ConnectorType.shopify)


def connect_webflow(db: Session, website: Website, site_id: str, access_token: str) -> WebsiteConnection:
    candidate = WebflowCredentials(site_id=site_id, access_token=access_token)
    try:
        webflow.verify_credentials(candidate)
    except ConnectorError as exc:
        raise ValueError(f"Could not verify Webflow credentials: {exc}") from exc

    encrypted = encrypt_text(json.dumps({"access_token": access_token}))
    return _upsert_connection(
        db,
        website,
        ConnectorType.webflow,
        encrypted_secret=encrypted,
        config={"site_id": site_id},
        granted_scopes=["pages:read", "pages:write"],
    )


def get_webflow_credentials(db: Session, website: Website) -> WebflowCredentials:
    connection = _get_connection_or_raise(db, website, ConnectorType.webflow)
    stored = json.loads(decrypt_text(connection.encrypted_secret_reference))
    return WebflowCredentials(site_id=connection.config_json["site_id"], access_token=stored["access_token"])


def disconnect_webflow(db: Session, website: Website) -> None:
    _disconnect(db, website, ConnectorType.webflow)


def connect_github(
    db: Session, website: Website, owner: str, repo: str, base_branch: str, access_token: str
) -> WebsiteConnection:
    candidate = GitHubCredentials(owner=owner, repo=repo, base_branch=base_branch, access_token=access_token)
    try:
        github_pr.verify_credentials(candidate)
    except ConnectorError as exc:
        raise ValueError(f"Could not verify GitHub credentials: {exc}") from exc

    encrypted = encrypt_text(json.dumps({"access_token": access_token}))
    return _upsert_connection(
        db,
        website,
        ConnectorType.github,
        encrypted_secret=encrypted,
        config={"owner": owner, "repo": repo, "base_branch": base_branch},
        granted_scopes=["contents:write", "pull_requests:write"],
    )


def get_github_credentials(db: Session, website: Website) -> GitHubCredentials:
    connection = _get_connection_or_raise(db, website, ConnectorType.github)
    stored = json.loads(decrypt_text(connection.encrypted_secret_reference))
    config = connection.config_json
    return GitHubCredentials(
        owner=config["owner"],
        repo=config["repo"],
        base_branch=config["base_branch"],
        access_token=stored["access_token"],
    )


def disconnect_github(db: Session, website: Website) -> None:
    _disconnect(db, website, ConnectorType.github)


def get_connected_content_connector(db: Session, website: Website) -> ConnectorType | None:
    """Which connector type is currently connected for this website, if
    any, preferring `CONTENT_CONNECTOR_PRIORITY` order if somehow more
    than one is connected at once.
    """
    connected = {
        c.connector_type
        for c in db.query(WebsiteConnection)
        .filter(WebsiteConnection.website_id == website.id, WebsiteConnection.status == WebsiteConnectionStatus.connected)
        .all()
    }
    for connector_type in CONTENT_CONNECTOR_PRIORITY:
        if connector_type in connected:
            return connector_type
    return None


def get_connector_credentials(db: Session, website: Website, connector_type: ConnectorType):
    if connector_type == ConnectorType.wordpress:
        return get_wordpress_credentials(db, website)
    if connector_type == ConnectorType.shopify:
        return get_shopify_credentials(db, website)
    if connector_type == ConnectorType.webflow:
        return get_webflow_credentials(db, website)
    if connector_type == ConnectorType.github:
        return get_github_credentials(db, website)
    raise LookupError(f"Unknown connector type: {connector_type}")
