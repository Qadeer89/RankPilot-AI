"""SSRF hardening for the Shopify/Sanity/WordPress connectors
(RP13-followup security review): a connector's user-supplied host field
must be rejected, both by schema-level character restriction and by
the connector's own pinned-request SSRF check, if it points at a
private/internal address."""

import socket

import pytest

from app.connectors import shopify, wordpress
from app.core import url_safety
from app.core.url_safety import UnsafeUrlError
from app.schemas.execution import SanityConnectRequest, ShopifyConnectRequest


def _stub_dns_private(monkeypatch):
    def fake_getaddrinfo(host, port):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", 0))]

    monkeypatch.setattr(url_safety.socket, "getaddrinfo", fake_getaddrinfo)


# --- Schema-level character restriction ---------------------------------


@pytest.mark.parametrize(
    "shop_domain",
    [
        "my-shop.myshopify.com",
        "shop123.example.com",
    ],
)
def test_shopify_schema_accepts_valid_domains(shop_domain):
    ShopifyConnectRequest(shop_domain=shop_domain, access_token="shpat_abc")


@pytest.mark.parametrize(
    "shop_domain",
    [
        "shop.com/../../internal",
        "shop.com@evil.com",
        "shop.com:8080/x y",
        "shop.com\nHost: internal",
    ],
)
def test_shopify_schema_rejects_domains_with_unsafe_characters(shop_domain):
    with pytest.raises(ValueError):
        ShopifyConnectRequest(shop_domain=shop_domain, access_token="shpat_abc")


def test_sanity_schema_accepts_valid_project_id_and_dataset():
    SanityConnectRequest(project_id="abc123", dataset="production", token="t")


@pytest.mark.parametrize("project_id", ["ABC123", "abc_123", "abc.123", "abc/123", "abc:123"])
def test_sanity_schema_rejects_project_id_outside_allowed_charset(project_id):
    with pytest.raises(ValueError):
        SanityConnectRequest(project_id=project_id, dataset="production", token="t")


# --- Connector-level SSRF check (pinned_request), beyond schema ---------


def test_shopify_connector_rejects_private_ip_shop_domain(monkeypatch):
    _stub_dns_private(monkeypatch)
    credentials = shopify.ShopifyCredentials(shop_domain="internal.example.com", access_token="shpat_abc")
    with pytest.raises(Exception):
        shopify.verify_credentials(credentials)


def test_shopify_connector_rejects_literal_private_ip():
    credentials = shopify.ShopifyCredentials(shop_domain="127.0.0.1", access_token="shpat_abc")
    with pytest.raises(Exception):
        shopify.verify_credentials(credentials)


def test_wordpress_connector_rejects_private_ip_site_url(monkeypatch):
    _stub_dns_private(monkeypatch)
    credentials = wordpress.WordPressCredentials(
        site_url="https://internal.example.com/", username="u", application_password="p"
    )
    with pytest.raises(Exception):
        wordpress.verify_credentials(credentials)


def test_pinned_request_is_the_mechanism_behind_the_rejection(monkeypatch):
    # Confirms the rejection specifically comes from SSRF validation
    # (UnsafeUrlError wrapped as a connector error), not some other
    # unrelated failure that happens to also raise.
    _stub_dns_private(monkeypatch)

    from app.connectors.errors import ConnectorError

    credentials = shopify.ShopifyCredentials(shop_domain="internal.example.com", access_token="shpat_abc")
    with pytest.raises(ConnectorError, match="unsafe"):
        shopify.verify_credentials(credentials)
