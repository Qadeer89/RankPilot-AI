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
        wp,
        "pinned_request",
        lambda method, url, auth=None, timeout=None: _FakeResponse(200, {"id": 1, "name": "RankPilot"}),
    )
    user = wp.verify_credentials(CREDENTIALS)
    assert user["name"] == "RankPilot"


def test_verify_credentials_failure(monkeypatch):
    monkeypatch.setattr(wp, "pinned_request", lambda *a, **k: _FakeResponse(401, {"code": "invalid"}))
    with pytest.raises(wp.WordPressConnectorError):
        wp.verify_credentials(CREDENTIALS)


def test_verify_credentials_network_failure_raises_connector_error_not_httpx_error(monkeypatch):
    import httpx

    def fake_pinned_request(*a, **k):
        raise httpx.ConnectError("DNS resolution failed")

    monkeypatch.setattr(wp, "pinned_request", fake_pinned_request)
    with pytest.raises(wp.WordPressConnectorError):
        wp.verify_credentials(CREDENTIALS)


def test_verify_credentials_unsafe_url_raises_connector_error(monkeypatch):
    # RP13-007 extended to connectors: a site_url that fails SSRF
    # validation (e.g. rebound to an internal address between connect
    # and execution time) must surface as a connector error, not an
    # unhandled UnsafeUrlError.
    from app.core.url_safety import UnsafeUrlError

    def fake_pinned_request(*a, **k):
        raise UnsafeUrlError("Host resolves to a disallowed address")

    monkeypatch.setattr(wp, "pinned_request", fake_pinned_request)
    with pytest.raises(wp.WordPressConnectorError):
        wp.verify_credentials(CREDENTIALS)


def test_find_post_by_url_checks_pages_then_posts(monkeypatch):
    calls = []

    def fake_pinned_request(method, url, params=None, auth=None, timeout=None):
        calls.append(url)
        if "/pages" in url:
            return _FakeResponse(200, [])
        if "/posts" in url:
            return _FakeResponse(200, [{"id": 42}])
        return _FakeResponse(404, {})

    monkeypatch.setattr(wp, "pinned_request", fake_pinned_request)
    post_type, post_id = wp.find_post_by_url(CREDENTIALS, "https://example.com/my-post")
    assert post_type == "posts"
    assert post_id == 42
    assert any("/pages" in c for c in calls)
    assert any("/posts" in c for c in calls)


def test_find_post_by_url_raises_when_not_found(monkeypatch):
    monkeypatch.setattr(wp, "pinned_request", lambda *a, **k: _FakeResponse(200, []))
    with pytest.raises(wp.WordPressConnectorError):
        wp.find_post_by_url(CREDENTIALS, "https://example.com/nowhere")


def test_update_title_success(monkeypatch):
    def fake_pinned_request(method, url, auth=None, json=None, timeout=None):
        assert method == "POST"
        assert json == {"title": "New Title"}
        return _FakeResponse(200, {"id": 42, "title": {"rendered": "New Title"}})

    monkeypatch.setattr(wp, "pinned_request", fake_pinned_request)
    result = wp.update_title(CREDENTIALS, "pages", 42, "New Title")
    assert wp.current_title(result) == "New Title"


def test_update_meta_description_rejects_unsupported_site(monkeypatch):
    monkeypatch.setattr(wp, "pinned_request", lambda *a, **k: _FakeResponse(400, {"code": "rest_invalid_param"}))
    with pytest.raises(wp.UnsupportedOperation):
        wp.update_meta_description(CREDENTIALS, "pages", 42, "A new description")


def test_update_meta_description_detects_silent_no_op(monkeypatch):
    # WordPress returns 200 but the meta key isn't actually registered, so
    # the value silently doesn't change.
    monkeypatch.setattr(
        wp, "pinned_request", lambda *a, **k: _FakeResponse(200, {"id": 42, "meta": {}})
    )
    with pytest.raises(wp.UnsupportedOperation):
        wp.update_meta_description(CREDENTIALS, "pages", 42, "A new description")


def test_update_meta_description_success(monkeypatch):
    monkeypatch.setattr(
        wp,
        "pinned_request",
        lambda *a, **k: _FakeResponse(200, {"id": 42, "meta": {"_yoast_wpseo_metadesc": "A new description"}}),
    )
    result = wp.update_meta_description(CREDENTIALS, "pages", 42, "A new description")
    assert wp.current_meta_description(result) == "A new description"


def test_find_media_by_url_matches_on_exact_source_url(monkeypatch):
    def fake_pinned_request(method, url, params=None, auth=None, timeout=None):
        assert "/media" in url
        assert params == {"search": "hero"}
        return _FakeResponse(
            200,
            [
                {"id": 7, "source_url": "https://example.com/wp-content/uploads/hero.jpg"},
                {"id": 8, "source_url": "https://example.com/wp-content/uploads/hero-2.jpg"},
            ],
        )

    monkeypatch.setattr(wp, "pinned_request", fake_pinned_request)
    media_id = wp.find_media_by_url(CREDENTIALS, "https://example.com/wp-content/uploads/hero.jpg")
    assert media_id == 7


def test_find_media_by_url_raises_when_no_candidate_actually_matches(monkeypatch):
    # A search match on filename stem alone isn't proof: a different image
    # with the same stem but a different extension/path must not be
    # mistaken for the one we're looking for.
    monkeypatch.setattr(
        wp,
        "pinned_request",
        lambda *a, **k: _FakeResponse(
            200, [{"id": 7, "source_url": "https://example.com/uploads/hero-unrelated.png"}]
        ),
    )
    with pytest.raises(wp.WordPressConnectorError):
        wp.find_media_by_url(CREDENTIALS, "https://example.com/uploads/hero.jpg")


def test_find_media_by_url_raises_when_search_finds_nothing(monkeypatch):
    monkeypatch.setattr(wp, "pinned_request", lambda *a, **k: _FakeResponse(200, []))
    with pytest.raises(wp.WordPressConnectorError):
        wp.find_media_by_url(CREDENTIALS, "https://example.com/uploads/missing.jpg")


def test_update_alt_text_success(monkeypatch):
    def fake_pinned_request(method, url, auth=None, json=None, timeout=None):
        assert "/media/7" in url
        assert json == {"alt_text": "A golden retriever on the beach"}
        return _FakeResponse(200, {"id": 7, "alt_text": "A golden retriever on the beach"})

    monkeypatch.setattr(wp, "pinned_request", fake_pinned_request)
    result = wp.update_alt_text(CREDENTIALS, 7, "A golden retriever on the beach")
    assert wp.current_alt_text(result) == "A golden retriever on the beach"


def test_update_alt_text_detects_silent_no_op(monkeypatch):
    monkeypatch.setattr(wp, "pinned_request", lambda *a, **k: _FakeResponse(200, {"id": 7, "alt_text": ""}))
    with pytest.raises(wp.UnsupportedOperation):
        wp.update_alt_text(CREDENTIALS, 7, "A golden retriever on the beach")


def test_update_canonical_success(monkeypatch):
    def fake_pinned_request(method, url, auth=None, json=None, timeout=None):
        assert json == {"meta": {wp.YOAST_CANONICAL_KEY: "https://example.com/real-page"}}
        return _FakeResponse(200, {"id": 42, "meta": {wp.YOAST_CANONICAL_KEY: "https://example.com/real-page"}})

    monkeypatch.setattr(wp, "pinned_request", fake_pinned_request)
    result = wp.update_canonical(CREDENTIALS, "pages", 42, "https://example.com/real-page")
    assert wp.current_canonical(result) == "https://example.com/real-page"


def test_update_canonical_rejects_unsupported_site(monkeypatch):
    monkeypatch.setattr(wp, "pinned_request", lambda *a, **k: _FakeResponse(400, {"code": "rest_invalid_param"}))
    with pytest.raises(wp.UnsupportedOperation):
        wp.update_canonical(CREDENTIALS, "pages", 42, "https://example.com/real-page")


def test_update_canonical_detects_silent_no_op(monkeypatch):
    monkeypatch.setattr(wp, "pinned_request", lambda *a, **k: _FakeResponse(200, {"id": 42, "meta": {}}))
    with pytest.raises(wp.UnsupportedOperation):
        wp.update_canonical(CREDENTIALS, "pages", 42, "https://example.com/real-page")
