import uuid
from datetime import date

import pytest

from app.integrations import google_analytics as ga4
from app.integrations import google_oauth_common


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None, text: str = ""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text or str(payload)

    def json(self):
        return self._payload


def test_build_authorization_url_uses_ga4_scope_and_redirect():
    org_id = uuid.uuid4()
    url = ga4.build_authorization_url(org_id)
    import httpx

    parsed = httpx.URL(url)
    assert parsed.params["scope"] == ga4.SCOPE
    assert "analytics" in parsed.params["redirect_uri"]
    assert ga4.decode_state(parsed.params["state"]) == org_id


def test_build_authorization_url_requires_configuration(monkeypatch):
    class _Unconfigured:
        google_client_id = None
        google_client_secret = None

    monkeypatch.setattr(google_oauth_common, "get_settings", lambda: _Unconfigured())
    with pytest.raises(ga4.GoogleIntegrationNotConfigured):
        ga4.build_authorization_url(uuid.uuid4())


def test_list_properties_flattens_account_summaries(monkeypatch):
    def fake_get(url, headers=None, params=None, timeout=None):
        assert headers["Authorization"] == "Bearer access-123"
        return _FakeResponse(
            200,
            {
                "accountSummaries": [
                    {
                        "propertySummaries": [
                            {"property": "properties/111", "displayName": "Site A"},
                            {"property": "properties/222", "displayName": "Site B"},
                        ]
                    }
                ]
            },
        )

    monkeypatch.setattr(ga4.httpx, "get", fake_get)
    properties = ga4.list_properties("access-123")
    assert properties == [
        {"property_id": "properties/111", "display_name": "Site A"},
        {"property_id": "properties/222", "display_name": "Site B"},
    ]


def test_list_properties_surfaces_http_errors(monkeypatch):
    monkeypatch.setattr(ga4.httpx, "get", lambda *a, **k: _FakeResponse(403, {"error": "forbidden"}))
    with pytest.raises(ga4.GoogleApiError):
        ga4.list_properties("access-123")


def test_run_report(monkeypatch):
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        return _FakeResponse(
            200,
            {
                "rows": [
                    {
                        "dimensionValues": [{"value": "20261001"}],
                        "metricValues": [{"value": "42"}, {"value": "30"}, {"value": "5"}],
                    }
                ]
            },
        )

    monkeypatch.setattr(ga4.httpx, "post", fake_post)
    rows = ga4.run_report(
        "access-123", "properties/111", start_date=date(2026, 10, 1), end_date=date(2026, 10, 28)
    )
    assert rows == [{"dimension_values": ["20261001"], "metric_values": ["42", "30", "5"]}]
    assert captured["url"] == f"{ga4.ANALYTICS_DATA_API_BASE}/properties/111:runReport"
