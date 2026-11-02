import uuid
from datetime import date

import httpx
import pytest

from app.config import get_settings
from app.integrations import google_oauth_common
from app.integrations import google_search_console as gsc


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None, text: str = ""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text or str(payload)

    def json(self):
        return self._payload


def test_build_authorization_url_contains_expected_params():
    org_id = uuid.uuid4()
    url = gsc.build_authorization_url(org_id)
    parsed = httpx.URL(url)
    assert parsed.host == "accounts.google.com"
    assert parsed.params["client_id"] == get_settings().google_client_id
    assert parsed.params["scope"] == gsc.SCOPE
    assert parsed.params["access_type"] == "offline"
    assert gsc.decode_state(parsed.params["state"]) == org_id


def test_build_authorization_url_requires_configuration(monkeypatch):
    class _UnconfiguredSettings:
        google_client_id = None
        google_client_secret = None

    monkeypatch.setattr(google_oauth_common, "get_settings", lambda: _UnconfiguredSettings())
    with pytest.raises(gsc.GoogleIntegrationNotConfigured):
        gsc.build_authorization_url(uuid.uuid4())


def test_decode_state_rejects_invalid_token():
    with pytest.raises(gsc.GoogleApiError):
        gsc.decode_state("not-a-real-jwt")


def test_exchange_code_for_tokens(monkeypatch):
    def fake_post(url, data=None, json=None, headers=None, timeout=None):
        assert url == google_oauth_common.TOKEN_ENDPOINT
        assert data["grant_type"] == "authorization_code"
        return _FakeResponse(
            200,
            {
                "access_token": "access-123",
                "refresh_token": "refresh-456",
                "expires_in": 3600,
                "scope": gsc.SCOPE,
                "token_type": "Bearer",
            },
        )

    monkeypatch.setattr(google_oauth_common.httpx, "post", fake_post)
    token_set = gsc.exchange_code_for_tokens("some-code")
    assert token_set.access_token == "access-123"
    assert token_set.refresh_token == "refresh-456"


def test_exchange_code_for_tokens_surfaces_http_errors(monkeypatch):
    monkeypatch.setattr(
        google_oauth_common.httpx, "post", lambda *a, **k: _FakeResponse(400, {"error": "invalid_grant"})
    )
    with pytest.raises(gsc.GoogleApiError):
        gsc.exchange_code_for_tokens("bad-code")


def test_list_sites(monkeypatch):
    def fake_get(url, headers=None, timeout=None):
        assert headers["Authorization"] == "Bearer access-123"
        return _FakeResponse(200, {"siteEntry": [{"siteUrl": "https://example.com/"}]})

    monkeypatch.setattr(gsc.httpx, "get", fake_get)
    assert gsc.list_sites("access-123") == ["https://example.com/"]


def test_query_search_analytics(monkeypatch):
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        return _FakeResponse(
            200,
            {"rows": [{"keys": ["rankpilot", "2026-10-01"], "clicks": 5, "impressions": 100, "ctr": 0.05, "position": 8.2}]},
        )

    monkeypatch.setattr(gsc.httpx, "post", fake_post)
    rows = gsc.query_search_analytics(
        "access-123",
        "https://example.com/",
        start_date=date(2026, 10, 1),
        end_date=date(2026, 10, 28),
    )
    assert rows[0]["keys"] == ["rankpilot", "2026-10-01"]
    assert "sites/https%3A%2F%2Fexample.com%2F/searchAnalytics/query" in captured["url"]
    assert captured["json"]["dimensions"] == ["query", "date"]
