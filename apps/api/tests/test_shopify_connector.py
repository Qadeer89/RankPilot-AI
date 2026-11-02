from app.connectors import shopify
from app.connectors.errors import ConnectorError


class _FakeResponse:
    def __init__(self, status_code: int, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = str(payload)

    def json(self):
        return self._payload


CREDENTIALS = shopify.ShopifyCredentials(shop_domain="rankpilot-test.myshopify.com", access_token="shpat_abc123")


def test_verify_credentials_success(monkeypatch):
    monkeypatch.setattr(shopify.httpx, "get", lambda *a, **k: _FakeResponse(200, {"shop": {"id": 1}}))
    result = shopify.verify_credentials(CREDENTIALS)
    assert result["shop"]["id"] == 1


def test_verify_credentials_failure_raises(monkeypatch):
    monkeypatch.setattr(shopify.httpx, "get", lambda *a, **k: _FakeResponse(401, {"errors": "Unauthorized"}))
    try:
        shopify.verify_credentials(CREDENTIALS)
        assert False, "expected ConnectorError"
    except ConnectorError:
        pass


def test_verify_credentials_network_failure_raises_connector_error_not_httpx_error(monkeypatch):
    import httpx

    def fake_get(*a, **k):
        raise httpx.ConnectError("DNS resolution failed")

    monkeypatch.setattr(shopify.httpx, "get", fake_get)
    try:
        shopify.verify_credentials(CREDENTIALS)
        assert False, "expected ConnectorError"
    except ConnectorError:
        pass
    except httpx.ConnectError:
        assert False, "network-level httpx errors must be wrapped as ConnectorError, not leak through"


def test_find_target_matches_page_by_handle(monkeypatch):
    def fake_get(url, params=None, headers=None, timeout=None):
        if "/pages.json" in url:
            return _FakeResponse(200, {"pages": [{"id": 55}]})
        return _FakeResponse(200, {"products": []})

    monkeypatch.setattr(shopify.httpx, "get", fake_get)
    target = shopify.find_target(CREDENTIALS, "https://rankpilot-test.myshopify.com/pages/about-us")
    assert target == {"resource_type": "pages", "resource_id": 55}


def test_find_target_falls_back_to_products(monkeypatch):
    def fake_get(url, params=None, headers=None, timeout=None):
        if "/pages.json" in url:
            return _FakeResponse(200, {"pages": []})
        return _FakeResponse(200, {"products": [{"id": 99}]})

    monkeypatch.setattr(shopify.httpx, "get", fake_get)
    target = shopify.find_target(CREDENTIALS, "https://rankpilot-test.myshopify.com/products/widget")
    assert target == {"resource_type": "products", "resource_id": 99}


def test_find_target_raises_when_nothing_matches(monkeypatch):
    monkeypatch.setattr(shopify.httpx, "get", lambda *a, **k: _FakeResponse(200, {"pages": [], "products": []}))
    try:
        shopify.find_target(CREDENTIALS, "https://rankpilot-test.myshopify.com/nothing")
        assert False, "expected ConnectorError"
    except ConnectorError:
        pass


def test_apply_change_creates_metafield_when_none_exists(monkeypatch):
    created = {}

    def fake_get(url, params=None, headers=None, timeout=None):
        return _FakeResponse(200, {"metafields": []})

    def fake_post(url, json=None, headers=None, timeout=None):
        created["url"] = url
        created["json"] = json
        return _FakeResponse(201, {"metafield": {"id": 1, "value": json["metafield"]["value"]}})

    monkeypatch.setattr(shopify.httpx, "get", fake_get)
    monkeypatch.setattr(shopify.httpx, "post", fake_post)

    target_ref = {"resource_type": "pages", "resource_id": 55}
    shopify.apply_change(CREDENTIALS, target_ref, "set_title", "New SEO Title")

    assert created["json"]["metafield"]["namespace"] == "global"
    assert created["json"]["metafield"]["key"] == "title_tag"
    assert created["json"]["metafield"]["value"] == "New SEO Title"


def test_apply_change_updates_existing_metafield(monkeypatch):
    updated = {}

    def fake_get(url, params=None, headers=None, timeout=None):
        return _FakeResponse(200, {"metafields": [{"id": 42, "value": "Old description"}]})

    def fake_put(url, json=None, headers=None, timeout=None):
        updated["url"] = url
        updated["json"] = json
        return _FakeResponse(200, {"metafield": {"id": 42, "value": json["metafield"]["value"]}})

    monkeypatch.setattr(shopify.httpx, "get", fake_get)
    monkeypatch.setattr(shopify.httpx, "put", fake_put)

    target_ref = {"resource_type": "products", "resource_id": 99}
    shopify.apply_change(CREDENTIALS, target_ref, "set_meta_description", "New description")

    assert "metafields/42.json" in updated["url"]
    assert updated["json"]["metafield"]["key"] == "description_tag"


def test_validate_change_compares_current_value(monkeypatch):
    monkeypatch.setattr(
        shopify.httpx, "get", lambda *a, **k: _FakeResponse(200, {"metafields": [{"id": 1, "value": "New Title"}]})
    )
    passed, evidence = shopify.validate_change(
        CREDENTIALS, {"resource_type": "pages", "resource_id": 55}, "set_title", "New Title", {}
    )
    assert passed is True
    assert evidence["actual"] == "New Title"


def test_rollback_restores_before_value(monkeypatch):
    restored = {}

    def fake_get(url, params=None, headers=None, timeout=None):
        return _FakeResponse(200, {"metafields": [{"id": 1, "value": "New Title"}]})

    def fake_put(url, json=None, headers=None, timeout=None):
        restored["value"] = json["metafield"]["value"]
        return _FakeResponse(200, {"metafield": {"id": 1, "value": json["metafield"]["value"]}})

    monkeypatch.setattr(shopify.httpx, "get", fake_get)
    monkeypatch.setattr(shopify.httpx, "put", fake_put)

    shopify.rollback(CREDENTIALS, {"resource_type": "pages", "resource_id": 55}, "set_title", "Old Title", {})
    assert restored["value"] == "Old Title"
