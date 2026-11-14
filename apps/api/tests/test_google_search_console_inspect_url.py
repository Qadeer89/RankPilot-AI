import pytest

from app.integrations import google_search_console as gsc


class _FakeResponse:
    def __init__(self, status_code: int, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = str(payload)

    def json(self):
        return self._payload


def test_inspect_url_returns_the_inspection_result(monkeypatch):
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        return _FakeResponse(200, {"inspectionResult": {"indexStatusResult": {"verdict": "PASS"}}})

    monkeypatch.setattr(gsc.httpx, "post", fake_post)

    result = gsc.inspect_url("token-1", "sc-domain:example.com", "https://example.com/about")

    assert result == {"indexStatusResult": {"verdict": "PASS"}}
    assert captured["url"] == f"{gsc.URL_INSPECTION_API_BASE}/urlInspection/index:inspect"
    assert captured["json"] == {"inspectionUrl": "https://example.com/about", "siteUrl": "sc-domain:example.com"}
    assert captured["headers"]["Authorization"] == "Bearer token-1"


def test_inspect_url_raises_on_http_error(monkeypatch):
    monkeypatch.setattr(gsc.httpx, "post", lambda *a, **k: _FakeResponse(403, {"error": "forbidden"}))

    with pytest.raises(gsc.GoogleApiError, match="HTTP 403"):
        gsc.inspect_url("token-1", "sc-domain:example.com", "https://example.com/about")


def test_inspect_url_returns_empty_dict_when_result_key_is_absent(monkeypatch):
    monkeypatch.setattr(gsc.httpx, "post", lambda *a, **k: _FakeResponse(200, {}))

    result = gsc.inspect_url("token-1", "sc-domain:example.com", "https://example.com/about")
    assert result == {}
