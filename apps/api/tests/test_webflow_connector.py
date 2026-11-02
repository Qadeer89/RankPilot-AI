from app.connectors import webflow
from app.connectors.errors import ConnectorError, UnsupportedOperation


class _FakeResponse:
    def __init__(self, status_code: int, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = str(payload)

    def json(self):
        return self._payload


CREDENTIALS = webflow.WebflowCredentials(site_id="site123", access_token="wf_token_abc")


def test_verify_credentials_success(monkeypatch):
    monkeypatch.setattr(webflow.httpx, "get", lambda *a, **k: _FakeResponse(200, {"id": "site123"}))
    result = webflow.verify_credentials(CREDENTIALS)
    assert result["id"] == "site123"


def test_verify_credentials_failure_raises(monkeypatch):
    monkeypatch.setattr(webflow.httpx, "get", lambda *a, **k: _FakeResponse(401, {}))
    try:
        webflow.verify_credentials(CREDENTIALS)
        assert False, "expected ConnectorError"
    except ConnectorError:
        pass


def test_verify_credentials_network_failure_raises_connector_error_not_httpx_error(monkeypatch):
    import httpx

    def fake_get(*a, **k):
        raise httpx.ConnectError("DNS resolution failed")

    monkeypatch.setattr(webflow.httpx, "get", fake_get)
    try:
        webflow.verify_credentials(CREDENTIALS)
        assert False, "expected ConnectorError"
    except ConnectorError:
        pass
    except httpx.ConnectError:
        assert False, "network-level httpx errors must be wrapped as ConnectorError, not leak through"


def test_find_target_matches_by_slug(monkeypatch):
    monkeypatch.setattr(
        webflow.httpx, "get", lambda *a, **k: _FakeResponse(200, {"pages": [{"id": "page1", "slug": "about"}]})
    )
    target = webflow.find_target(CREDENTIALS, "https://example.com/about")
    assert target == {"page_id": "page1"}


def test_find_target_raises_when_no_match(monkeypatch):
    monkeypatch.setattr(webflow.httpx, "get", lambda *a, **k: _FakeResponse(200, {"pages": []}))
    try:
        webflow.find_target(CREDENTIALS, "https://example.com/missing")
        assert False, "expected ConnectorError"
    except ConnectorError:
        pass


def test_get_current_value_title_and_description(monkeypatch):
    monkeypatch.setattr(
        webflow.httpx,
        "get",
        lambda *a, **k: _FakeResponse(200, {"title": "About Us", "seo": {"description": "Our story"}}),
    )
    assert webflow.get_current_value(CREDENTIALS, {"page_id": "page1"}, "set_title") == "About Us"
    assert webflow.get_current_value(CREDENTIALS, {"page_id": "page1"}, "set_meta_description") == "Our story"


def test_apply_change_patches_title(monkeypatch):
    sent = {}

    def fake_patch(url, json=None, headers=None, timeout=None):
        sent["url"] = url
        sent["json"] = json
        return _FakeResponse(200, {"id": "page1", "title": json["title"]})

    monkeypatch.setattr(webflow.httpx, "patch", fake_patch)
    webflow.apply_change(CREDENTIALS, {"page_id": "page1"}, "set_title", "New Title")
    assert sent["json"] == {"title": "New Title"}


def test_apply_change_patches_meta_description(monkeypatch):
    sent = {}

    def fake_patch(url, json=None, headers=None, timeout=None):
        sent["json"] = json
        return _FakeResponse(200, {"id": "page1", "seo": json["seo"]})

    monkeypatch.setattr(webflow.httpx, "patch", fake_patch)
    webflow.apply_change(CREDENTIALS, {"page_id": "page1"}, "set_meta_description", "New description")
    assert sent["json"] == {"seo": {"description": "New description"}}


def test_apply_change_raises_unsupported_operation_on_400(monkeypatch):
    monkeypatch.setattr(webflow.httpx, "patch", lambda *a, **k: _FakeResponse(400, {}))
    try:
        webflow.apply_change(CREDENTIALS, {"page_id": "page1"}, "set_title", "New Title")
        assert False, "expected UnsupportedOperation"
    except UnsupportedOperation:
        pass


def test_rollback_restores_before_value(monkeypatch):
    sent = {}

    def fake_patch(url, json=None, headers=None, timeout=None):
        sent["json"] = json
        return _FakeResponse(200, {"id": "page1", "title": json["title"]})

    monkeypatch.setattr(webflow.httpx, "patch", fake_patch)
    webflow.rollback(CREDENTIALS, {"page_id": "page1"}, "set_title", "Old Title", {})
    assert sent["json"] == {"title": "Old Title"}
