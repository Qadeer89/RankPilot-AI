"""Shopify catalog SEO: connector paging, analysis rules, sync, API and tenant isolation (all against a fake store)."""

import uuid

import pytest

from app.connectors import shopify
from app.connectors.errors import ConnectorError
from app.models.history import ProductSnapshot
from app.models.website import Website
from app.shopify_seo import catalog
from tests.billing_helpers import register

CREDS = shopify.ShopifyCredentials(shop_domain="demo.myshopify.com", access_token="shpat_x")
LONG = " ".join(["word"] * 80)


class R:
    def __init__(self, status=200, payload=None, link=None):
        self.status_code, self._p, self.text = status, payload if payload is not None else {}, str(payload)
        self.headers = {"link": link} if link else {}

    def json(self):
        return self._p


class FakeStore:
    """Answers the Admin REST calls the catalog sync makes."""

    def __init__(self, products, collections=(), seo=None, fail=None):
        self.products, self.collections, self.seo, self.fail, self.calls = list(products), list(collections), seo or {}, fail, []

    def __call__(self, _fn, method, url, **kw):
        self.calls.append((method, url, kw.get("params")))
        if self.fail:
            return R(self.fail, {"errors": "x"})
        params = kw.get("params") or {}
        if url.endswith("/products.json"):
            if params.get("page_info") == "p2":
                return R(payload={"products": self.products[1:]})
            return R(payload={"products": self.products[:1]}, link='<https://demo.myshopify.com/admin/api/2024-01/products.json?page_info=p2&limit=250>; rel="next"') if len(self.products) > 1 else R(payload={"products": self.products})
        if url.endswith("/custom_collections.json"):
            return R(payload={"custom_collections": self.collections})
        if url.endswith("/smart_collections.json"):
            return R(payload={"smart_collections": []})
        if url.endswith("/metafields.json"):
            rid = url.split("/")[-2]
            key = params.get("key")
            value = self.seo.get((rid, key))
            return R(payload={"metafields": [{"id": 1, "value": value}] if value else []})
        return R(404, {})


@pytest.fixture
def store(monkeypatch):
    def install(**kw):
        s = FakeStore(**kw)
        monkeypatch.setattr(shopify, "safe_request", s)
        return s
    return install


def product(pid, title, body=LONG, images=({"alt": "a"},), status="active", handle=None):
    return {"id": pid, "title": title, "handle": handle or title.lower().replace(" ", "-"), "body_html": f"<p>{body}</p>" if body else "", "status": status, "images": list(images), "variants": []}


def test_paging_follows_the_link_header_and_stops(store):
    s = store(products=[product(1, "A"), product(2, "B")])
    assert [p["id"] for p in shopify.list_products(CREDS)] == [1, 2]
    assert [c[2].get("page_info") for c in s.calls] == [None, "p2"]
    assert shopify._next_page_info(None) is None and shopify._next_page_info('<x?page_info=abc&limit=5>; rel="previous"') is None


def test_api_errors_become_connector_errors(store):
    store(products=[], fail=401)
    with pytest.raises(ConnectorError):
        shopify.list_products(CREDS)


def test_product_rules_are_specific_and_do_not_overstate():
    codes = lambda p, t=None, m=None, dup=frozenset(): {i["code"] for i in catalog.product_issues(p, t, m, set(dup))}  # noqa: E731
    assert codes(product(1, "Fine"), "Fine title", "x" * 100) == set()
    assert "SEO_FIELDS_NOT_READ" in codes(product(1, "Fine"))  # not judged, and says so
    assert "META_MISSING" in codes(product(1, "Fine"), "t", "")
    assert "TITLE_TOO_LONG" in codes(product(1, "Fine"), "t" * 70, "x" * 100)
    assert "TITLE_TOO_LONG" in codes(product(1, "T" * 70), "", "x" * 100)  # falls back to the product title
    assert "DESCRIPTION_MISSING" in codes(product(1, "x", body=""), "t", "x" * 100)
    assert "DESCRIPTION_THIN" in codes(product(1, "x", body="few words here"), "t", "x" * 100)
    assert "NO_IMAGES" in codes(product(1, "x", images=()), "t", "x" * 100)
    assert "IMAGE_ALT_MISSING" in codes(product(1, "x", images=({"alt": ""}, {"alt": "ok"})), "t", "x" * 100)
    assert "DUPLICATE_TITLE" in codes(product(1, "Same"), "t", "x" * 100, dup={"same"})
    assert "NOT_PUBLISHED" in codes(product(1, "x", status="draft"), "t", "x" * 100)
    severity = {i["code"]: i["severity"] for i in catalog.product_issues(product(1, "x", body=""), "t", "x" * 100, set())}
    assert severity["DESCRIPTION_MISSING"] == "critical"


def test_sync_stores_a_snapshot_per_item_and_marks_unread_fields_not_judged(db_session, store):
    site = Website(organization_id=uuid.uuid4(), canonical_url="https://demo.example/", hostname="demo.example", display_name="Demo")
    from tests.ai_search_helpers import make_site
    site = make_site(db_session)
    store(products=[product(1, "Blue Mug"), product(2, "Blue Mug", body="")], collections=[{"id": 9, "title": "Mugs", "handle": "mugs", "body_html": ""}],
          seo={("1", "title_tag"): "Blue Mug | Shop", ("1", "description_tag"): "d" * 100})
    result = catalog.sync_catalog(db_session, site, CREDS)
    assert (result["products"], result["collections"]) == (2, 1)
    rows = {r.external_id: r for r in catalog.latest(db_session, site, ProductSnapshot)}
    assert rows["1"].seo_title == "Blue Mug | Shop" and "DUPLICATE_TITLE" in {i["code"] for i in rows["1"].issues_json}
    assert "DESCRIPTION_MISSING" in {i["code"] for i in rows["2"].issues_json}
    # a second sync keeps history: the older rows stay, latest() returns one per product
    catalog.sync_catalog(db_session, site, CREDS)
    assert db_session.query(ProductSnapshot).filter_by(website_id=site.id).count() == 4 and len(catalog.latest(db_session, site, ProductSnapshot)) == 2
    s = catalog.summary(db_session, site)
    assert s["products"] == 2 and s["collections"] == 1 and s["issue_counts"]["COLLECTION_DESCRIPTION_MISSING"] == 1


@pytest.fixture
def world(client, db_session, monkeypatch):
    headers, org = register(client, "shop-owner@example.com")
    site = Website(organization_id=uuid.UUID(org), canonical_url="https://demo.example/", hostname="demo.example", display_name="Demo")
    db_session.add(site)
    db_session.commit()
    return type("W", (), dict(headers=headers, org=org, site=site, base=f"/api/v1/organizations/{org}/websites/{site.id}/shopify", mp=monkeypatch))


def test_api_requires_a_connected_store(client, world):
    r = client.post(f"{world.base}/sync", headers=world.headers)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "shopify_not_connected"
    assert client.get(f"{world.base}/summary", headers=world.headers).json()["products"] == 0


def test_api_sync_and_browse(client, world, store):
    from app.execution import connections
    world.mp.setattr(connections, "get_shopify_credentials", lambda db, w: CREDS)
    store(products=[product(1, "Blue Mug"), product(2, "Red Mug", body="")], seo={("1", "title_tag"): "t", ("1", "description_tag"): "d" * 100})
    r = client.post(f"{world.base}/sync", headers=world.headers).json()
    assert r["products"] == 2 and r["summary"]["products_with_issues"] >= 1 and r["summary"]["last_synced_at"]
    items = client.get(f"{world.base}/catalog?kind=products", headers=world.headers).json()
    assert items["total"] == 2 and items["items"][0]["title"] == "Red Mug"  # most issues first
    only = client.get(f"{world.base}/catalog?issue=DESCRIPTION_MISSING", headers=world.headers).json()
    assert [i["title"] for i in only["items"]] == ["Red Mug"]
    assert client.get(f"{world.base}/catalog?kind=orders", headers=world.headers).status_code == 422


def test_store_failures_are_reported_without_a_partial_snapshot(client, db_session, world, store):
    from app.execution import connections
    world.mp.setattr(connections, "get_shopify_credentials", lambda db, w: CREDS)
    store(products=[], fail=403)
    r = client.post(f"{world.base}/sync", headers=world.headers)
    assert r.status_code == 502 and r.json()["detail"]["code"] == "shopify_error"
    assert db_session.query(ProductSnapshot).count() == 0


def test_other_workspaces_are_locked_out(client, world):
    other, _ = register(client, "shop-intruder@example.com")
    for method, path in (("get", "summary"), ("get", "catalog"), ("post", "sync")):
        assert getattr(client, method)(f"{world.base}/{path}", headers=other).status_code in (403, 404)
    assert client.get(f"{world.base}/summary").status_code == 401
