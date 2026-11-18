"""Shopify product and collection SEO analysis.

Deterministic checks over what the store itself reports. Nothing is invented: a field the store does not return is
"not available", and every issue names the exact field. A product with no SEO title set is not an error by itself,
because Shopify falls back to the product title; the check says so rather than overstating it. The sync only READS the
store."""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from datetime import datetime, timezone
from html import unescape

from sqlalchemy.orm import Session

from app.connectors import shopify
from app.models.history import CollectionSnapshot, ProductSnapshot
from app.models.website import Website

TITLE_MAX, META_MIN, META_MAX, THIN_WORDS, MAX_SYNC_PRODUCT_SEO_LOOKUPS = 60, 70, 160, 50, 300


def _text(html: str | None) -> str:
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", html or ""))).strip()


def _issue(code: str, severity: str, message: str, field: str) -> dict:
    return {"code": code, "severity": severity, "message": message, "field": field}


def product_issues(p: dict, seo_title: str | None, meta: str | None, duplicate_titles: set[str]) -> list[dict]:
    issues: list[dict] = []
    title, body = (p.get("title") or "").strip(), _text(p.get("body_html"))
    images = p.get("images") or []
    if seo_title is None and meta is None:
        issues.append(_issue("SEO_FIELDS_NOT_READ", "info", "The store's SEO title and meta description were not read for this product, so they are not judged.", "seo"))
    else:
        effective = (seo_title or "").strip() or title
        if len(effective) > TITLE_MAX:
            issues.append(_issue("TITLE_TOO_LONG", "warning", f"The search title is {len(effective)} characters; about {TITLE_MAX} display in results.", "seo_title"))
        if not (meta or "").strip():
            issues.append(_issue("META_MISSING", "warning", "No meta description is set, so search engines choose their own snippet.", "meta_description"))
        elif len(meta.strip()) < META_MIN or len(meta.strip()) > META_MAX:
            issues.append(_issue("META_LENGTH", "info", f"The meta description is {len(meta.strip())} characters; {META_MIN}-{META_MAX} usually displays well.", "meta_description"))
    words = len(body.split())
    if words == 0:
        issues.append(_issue("DESCRIPTION_MISSING", "critical", "The product has no description text.", "body_html"))
    elif words < THIN_WORDS:
        issues.append(_issue("DESCRIPTION_THIN", "warning", f"The description has only {words} words.", "body_html"))
    if not images:
        issues.append(_issue("NO_IMAGES", "warning", "The product has no images.", "images"))
    else:
        missing = sum(1 for i in images if not (i.get("alt") or "").strip())
        if missing:
            issues.append(_issue("IMAGE_ALT_MISSING", "warning", f"{missing} of {len(images)} image(s) have no alt text.", "images"))
    if title.lower() in duplicate_titles:
        issues.append(_issue("DUPLICATE_TITLE", "warning", "Another product has the same title.", "title"))
    if (p.get("status") or "active") != "active":
        issues.append(_issue("NOT_PUBLISHED", "info", f"The product status is '{p.get('status')}', so it is not for sale in search results yet.", "status"))
    return issues


def collection_issues(c: dict, seo_title: str | None, meta: str | None) -> list[dict]:
    issues: list[dict] = []
    if not _text(c.get("body_html")):
        issues.append(_issue("COLLECTION_DESCRIPTION_MISSING", "warning", "The collection has no description text for search engines to read.", "body_html"))
    if seo_title is not None or meta is not None:
        if not (meta or "").strip():
            issues.append(_issue("META_MISSING", "warning", "No meta description is set.", "meta_description"))
        if len((seo_title or c.get("title") or "").strip()) > TITLE_MAX:
            issues.append(_issue("TITLE_TOO_LONG", "warning", f"The search title is over {TITLE_MAX} characters.", "seo_title"))
    return issues


def sync_catalog(db: Session, website: Website, credentials: shopify.ShopifyCredentials, *, read_seo_fields: bool = True) -> dict:
    """Read the store and store one snapshot row per product/collection. Raises ConnectorError on API failure."""
    now = datetime.now(timezone.utc)
    products, collections = shopify.list_products(credentials), shopify.list_collections(credentials)
    base = f"https://{website.hostname}"
    counts = Counter((p.get("title") or "").strip().lower() for p in products)
    duplicates = {t for t, n in counts.items() if t and n > 1}
    lookups = 0
    out_products, out_collections = 0, 0
    for p in products:
        seo = {"seo_title": None, "meta_description": None}
        if read_seo_fields and lookups < MAX_SYNC_PRODUCT_SEO_LOOKUPS:
            seo, lookups = shopify.get_seo_fields(credentials, "products", p["id"]), lookups + 1
        body = _text(p.get("body_html"))
        db.add(ProductSnapshot(
            website_id=website.id, external_id=str(p["id"]), handle=p.get("handle"), url=f"{base}/products/{p.get('handle')}", title=p.get("title"),
            seo_title=seo["seo_title"], meta_description=seo["meta_description"], description_hash=hashlib.sha256(body.encode()).hexdigest() if body else None,
            description_excerpt=body[:300] or None, image_alts=[(i.get("alt") or "") for i in p.get("images") or []], availability=p.get("status"),
            issues_json=product_issues(p, seo["seo_title"], seo["meta_description"], duplicates), captured_at=now))
        out_products += 1
    for c in collections:
        seo = {"seo_title": None, "meta_description": None}
        if read_seo_fields:
            kind = "smart_collections" if c.get("rules") is not None else "collections"
            seo = shopify.get_seo_fields(credentials, kind, c["id"])
        body = _text(c.get("body_html"))
        db.add(CollectionSnapshot(
            website_id=website.id, external_id=str(c["id"]), handle=c.get("handle"), url=f"{base}/collections/{c.get('handle')}", title=c.get("title"),
            seo_title=seo["seo_title"], meta_description=seo["meta_description"], description_hash=hashlib.sha256(body.encode()).hexdigest() if body else None,
            product_count=None, issues_json=collection_issues(c, seo["seo_title"], seo["meta_description"]), captured_at=now))
        out_collections += 1
    db.flush()
    return {"products": out_products, "collections": out_collections, "captured_at": now.isoformat(), "seo_fields_read_for": lookups,
            "seo_fields_skipped": max(len(products) - lookups, 0) if read_seo_fields else len(products)}


def latest(db: Session, website: Website, model) -> list:
    """The most recent snapshot row for each product/collection."""
    rows = db.query(model).filter(model.website_id == website.id).order_by(model.captured_at.desc()).all()
    seen: dict[str, object] = {}
    for r in rows:
        seen.setdefault(r.external_id, r)
    return list(seen.values())


def summary(db: Session, website: Website) -> dict:
    products, collections = latest(db, website, ProductSnapshot), latest(db, website, CollectionSnapshot)
    by_code: Counter = Counter()
    for r in [*products, *collections]:
        for i in r.issues_json:
            by_code[i["code"]] += 1
    return {"products": len(products), "collections": len(collections), "products_with_issues": sum(1 for r in products if any(i["severity"] != "info" for i in r.issues_json)),
            "issue_counts": dict(by_code), "last_synced_at": max((r.captured_at for r in [*products, *collections]), default=None)}
