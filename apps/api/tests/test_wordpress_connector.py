import pytest

from app.connectors import wordpress as wp


class _FakeResponse:
    def __init__(self, status_code: int, payload=None, text: str = ""):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text or str(payload)

    def json(self):
        return self._payload


CREDENTIALS = wp.WordPressCredentials(
    site_url="https://example.com/", username="rankpilot", application_password="app-pass-123"
)


def test_verify_credentials_success(monkeypatch):
    monkeypatch.setattr(
        wp.httpx, "get", lambda url, auth=None, timeout=None: _FakeResponse(200, {"id": 1, "name": "RankPilot"})
    )
    user = wp.verify_credentials(CREDENTIALS)
    assert user["name"] == "RankPilot"


def test_verify_credentials_failure(monkeypatch):
    monkeypatch.setattr(wp.httpx, "get", lambda *a, **k: _FakeResponse(401, {"code": "invalid"}))
    with pytest.raises(wp.WordPressConnectorError):
        wp.verify_credentials(CREDENTIALS)


def test_find_post_by_url_checks_pages_then_posts(monkeypatch):
    calls = []

    def fake_get(url, params=None, auth=None, timeout=None):
        calls.append(url)
        if "/pages" in url:
            return _FakeResponse(200, [])
        if "/posts" in url:
            return _FakeResponse(200, [{"id": 42}])
        return _FakeResponse(404, {})

    monkeypatch.setattr(wp.httpx, "get", fake_get)
    post_type, post_id = wp.find_post_by_url(CREDENTIALS, "https://example.com/my-post")
    assert post_type == "posts"
    assert post_id == 42
    assert any("/pages" in c for c in calls)
    assert any("/posts" in c for c in calls)


def test_find_post_by_url_raises_when_not_found(monkeypatch):
    monkeypatch.setattr(wp.httpx, "get", lambda *a, **k: _FakeResponse(200, []))
    with pytest.raises(wp.WordPressConnectorError):
        wp.find_post_by_url(CREDENTIALS, "https://example.com/nowhere")


def test_update_title_success(monkeypatch):
    def fake_post(url, auth=None, json=None, timeout=None):
        assert json == {"title": "New Title"}
        return _FakeResponse(200, {"id": 42, "title": {"rendered": "New Title"}})

    monkeypatch.setattr(wp.httpx, "post", fake_post)
    result = wp.update_title(CREDENTIALS, "pages", 42, "New Title")
    assert wp.current_title(result) == "New Title"


def test_update_meta_description_rejects_unsupported_site(monkeypatch):
    monkeypatch.setattr(wp.httpx, "post", lambda *a, **k: _FakeResponse(400, {"code": "rest_invalid_param"}))
    with pytest.raises(wp.UnsupportedOperation):
        wp.update_meta_description(CREDENTIALS, "pages", 42, "A new description")


def test_update_meta_description_detects_silent_no_op(monkeypatch):
    # WordPress returns 200 but the meta key isn't actually registered, so
    # the value silently doesn't change.
    monkeypatch.setattr(
        wp.httpx, "post", lambda *a, **k: _FakeResponse(200, {"id": 42, "meta": {}})
    )
    with pytest.raises(wp.UnsupportedOperation):
        wp.update_meta_description(CREDENTIALS, "pages", 42, "A new description")


def test_update_meta_description_success(monkeypatch):
    monkeypatch.setattr(
        wp.httpx,
        "post",
        lambda *a, **k: _FakeResponse(200, {"id": 42, "meta": {"_yoast_wpseo_metadesc": "A new description"}}),
    )
    result = wp.update_meta_description(CREDENTIALS, "pages", 42, "A new description")
    assert wp.current_meta_description(result) == "A new description"
