"""Backlink records and verification, without any paid link index.

RankPilot cannot discover who links to a site: that needs a web-scale crawl nobody gets for free. What it can do honestly:
  1. take source URLs a person supplies (typed, pasted, or from a Search Console "Top linking sites / Latest links" export);
  2. fetch each source page (public URLs only, robots.txt respected, polite delay, size and time limits) and check whether
     it really links to this website, recording anchor text, rel attributes, destination and where in the page it sits;
  3. keep a check history so new, lost and changed links are shown with evidence.
Everything shown is therefore "verified from the source page" or "not checked"; there is no estimated total of backlinks."""

from __future__ import annotations

import csv
import io
import re
import time
from collections import Counter
from datetime import datetime, timezone
from typing import Callable
from urllib.parse import urlsplit

from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from app.core.url_safety import UnsafeUrlError, validate_public_url
from app.crawler.fetch import DEFAULT_USER_AGENT, FetchError, FetchResult, safe_fetch
from app.crawler.robots import fetch_robots_policy
from app.models.authority import Backlink, BacklinkCheck
from app.models.website import Website

MAX_IMPORT = 500
MAX_CHECKS_PER_CALL = 25
CHECK_DELAY_SECONDS = 0.5
TIME_BUDGET_SECONDS = 40
SOURCES = {"user_provided", "gsc_export", "public_page_scan"}
_URL = re.compile(r"https?://[^\s,;\"'<>]+", re.I)


def _host(url: str) -> str:
    h = (urlsplit(url).hostname or "").lower()
    return h[4:] if h.startswith("www.") else h


def _clean_source(url: str) -> str:
    p = urlsplit(url.strip())
    return f"{p.scheme.lower()}://{p.netloc.lower()}{p.path or '/'}" + (f"?{p.query}" if p.query else "")


def parse_urls(text: str) -> list[str]:
    """Pull http(s) URLs out of pasted text or a CSV (any column). Order kept, duplicates removed."""
    seen, out = set(), []
    for m in _URL.findall(text or ""):
        u = _clean_source(m.rstrip(").,"))
        if u not in seen:
            seen.add(u); out.append(u)
    return out


def parse_gsc_export(content: str) -> list[str]:
    """Search Console's links export is a CSV whose rows hold linking domains or pages. Only full URLs are kept; bare domains become a
    homepage URL so they can still be checked, and the person is told which ones were domains."""
    urls = parse_urls(content)
    if urls:
        return urls
    out = []
    for row in csv.reader(io.StringIO(content or "")):
        cell = (row[0] if row else "").strip()
        if re.fullmatch(r"[a-z0-9][a-z0-9.-]+\.[a-z]{2,}", cell, re.I):
            out.append(f"https://{cell.lower()}/")
    return list(dict.fromkeys(out))


def add_backlinks(db: Session, website: Website, urls: list[str], source: str) -> dict:
    if source not in SOURCES:
        raise ValueError("Unknown discovery source.")
    own = _host(website.canonical_url)
    now = datetime.now(timezone.utc)
    existing = {b.source_url for b in db.query(Backlink.source_url).filter(Backlink.website_id == website.id)}
    added, skipped_dup, rejected = [], 0, []
    for raw in urls[:MAX_IMPORT]:
        try:
            validate_public_url(raw)
        except UnsafeUrlError as exc:
            rejected.append({"url": raw, "reason": str(exc)}); continue
        url = _clean_source(raw)
        if _host(url) == own:
            rejected.append({"url": raw, "reason": "This is your own website, not an external backlink."}); continue
        if url in existing:
            skipped_dup += 1; continue
        existing.add(url)
        db.add(Backlink(website_id=website.id, source_url=url, source_domain=_host(url), rel_values=[], discovery_source=source, status="unchecked", first_discovered_at=now))
        added.append(url)
    db.flush()
    return {"added": len(added), "duplicates": skipped_dup, "rejected": rejected, "truncated": max(len(urls) - MAX_IMPORT, 0)}


def _location(a) -> str:
    for parent in a.parents:
        n = (parent.name or "").lower()
        if n in ("nav",): return "navigation"
        if n == "header": return "header"
        if n == "footer": return "footer"
        if n == "aside": return "sidebar"
    return "content"


def find_links_to_site(html: str, source_url: str, site_host: str) -> list[dict]:
    """Every anchor on the page whose destination is the site (or a subdomain-equal host)."""
    from urllib.parse import urljoin
    soup = BeautifulSoup(html or "", "html.parser")
    found = []
    for a in soup.find_all("a", href=True):
        dest = urljoin(source_url, a["href"])
        if _host(dest) != site_host:
            continue
        rel = sorted({r.lower() for r in (a.get("rel") or [])})
        text = a.get_text(" ", strip=True)
        if not text:
            img = a.find("img")
            text = f"[image] {img.get('alt', '').strip()}" if img and img.get("alt") else ""
        found.append({"target_url": dest.split("#")[0], "anchor_text": text[:300] or None, "rel_values": rel,
                      "is_nofollow": bool({"nofollow", "ugc", "sponsored"} & set(rel)), "link_location": _location(a)})
    return found


Fetcher = Callable[[str], FetchResult]


def check_backlink(db: Session, website: Website, bl: Backlink, *, fetcher: Fetcher | None = None, robots_cache: dict | None = None) -> BacklinkCheck:
    """Fetch the source page once and record what it shows. Never raises for a bad source: the outcome is the result."""
    fetch = fetcher or (lambda u: safe_fetch(u, user_agent=DEFAULT_USER_AGENT))
    robots_cache = robots_cache if robots_cache is not None else {}
    now = datetime.now(timezone.utc)
    site_host = _host(website.canonical_url)
    status, http, link, note = "error", None, None, None
    try:
        validate_public_url(bl.source_url)
        origin = f"{urlsplit(bl.source_url).scheme}://{urlsplit(bl.source_url).netloc}"
        if fetcher is None:
            policy = robots_cache.get(origin) or robots_cache.setdefault(origin, fetch_robots_policy(origin, user_agent=DEFAULT_USER_AGENT))
            if not policy.can_fetch(bl.source_url, DEFAULT_USER_AGENT):
                status, note = "blocked_by_robots", "The source site's robots.txt does not allow RankPilot to read this page, so the link was not checked."
                raise StopIteration
        res = fetch(bl.source_url)
        http = res.status_code
        if http >= 400:
            status, note = "unreachable", f"The source page answered with HTTP {http}."
        else:
            links = find_links_to_site(res.body, res.final_url, site_host)
            if links:
                status, link = "live", links[0]
                note = f"{len(links)} link(s) to your site found on this page." if len(links) > 1 else None
            else:
                status, note = "link_removed", "The page loads but no longer contains a link to your website."
    except StopIteration:
        pass
    except UnsafeUrlError as exc:
        status, note = "error", str(exc)
    except FetchError as exc:
        status, note = "unreachable", f"The source page could not be fetched: {exc}"
    except Exception as exc:  # a broken source must not stop the batch
        status, note = "error", f"Unexpected error while checking: {type(exc).__name__}"

    prev = {"status": bl.status, "target_url": bl.target_url, "anchor_text": bl.anchor_text, "rel_values": bl.rel_values}
    new = {"status": status, "target_url": link["target_url"] if link else bl.target_url if status != "live" else None,
           "anchor_text": link["anchor_text"] if link else bl.anchor_text, "rel_values": link["rel_values"] if link else bl.rel_values}
    changes = []
    if bl.last_checked_at is None:
        changes.append({"field": "first_check", "to": status})
    else:
        for field in ("status", "target_url", "anchor_text", "rel_values"):
            if status == "live" and prev[field] != new[field] or field == "status" and prev[field] != new[field]:
                changes.append({"field": field, "from": prev[field], "to": new[field]})
    if status in ("live", "link_removed"):  # only a loaded page tells us about the link itself
        if status == "live":
            bl.target_url, bl.anchor_text, bl.rel_values = new["target_url"], new["anchor_text"], new["rel_values"]
            bl.is_nofollow, bl.link_location = link["is_nofollow"], link["link_location"]
            bl.last_live_at, bl.lost_at = now, None
        else:
            bl.lost_at = bl.lost_at or now
    elif status == "unreachable" and bl.status == "live":
        note = (note or "") + " The link was live at the last successful check; it is not marked lost until the page loads without it."
    keep_live = status in ("unreachable", "error", "blocked_by_robots") and bl.status == "live"  # a temporary outage does not erase a live link
    if not keep_live:
        bl.status = status
    bl.http_status, bl.last_checked_at, bl.note = http, now, note
    check = BacklinkCheck(backlink_id=bl.id, website_id=website.id, checked_at=now, status=status, http_status=http, target_url=bl.target_url,
                          anchor_text=bl.anchor_text, rel_values=bl.rel_values, changes_json=changes)
    db.add(check)
    db.flush()
    return check


def check_batch(db: Session, website: Website, *, ids: list | None = None, fetcher: Fetcher | None = None, sleep: Callable[[float], None] = time.sleep) -> dict:
    """Check the least recently checked links first, within a count and time budget, so one call never becomes an unbounded crawl."""
    q = db.query(Backlink).filter(Backlink.website_id == website.id)
    if ids:
        q = q.filter(Backlink.id.in_(ids))
    rows = q.order_by(Backlink.last_checked_at.asc().nullsfirst()).limit(MAX_CHECKS_PER_CALL).all()
    started, done, cache = time.monotonic(), 0, {}
    for bl in rows:
        if time.monotonic() - started > TIME_BUDGET_SECONDS:
            break
        check_backlink(db, website, bl, fetcher=fetcher, robots_cache=cache)
        done += 1
        sleep(CHECK_DELAY_SECONDS if fetcher is None else 0)
    return {"checked": done, "remaining_in_batch": len(rows) - done}


def referring_domain_analysis(db: Session, website: Website) -> dict:
    rows = db.query(Backlink).filter(Backlink.website_id == website.id).all()
    live = [b for b in rows if b.status == "live"]
    domains = Counter(b.source_domain for b in live)
    follow = sum(1 for b in live if b.is_nofollow is False)
    anchors = Counter((b.anchor_text or "(no text)").lower() for b in live)
    dests = Counter(b.target_url for b in live if b.target_url)
    total_anchor = sum(anchors.values()) or 1
    by_status = Counter(b.status for b in rows)
    return {
        "label": "Verified from the source pages you listed. This is not a count of every link to your site; RankPilot has no web-wide link index.",
        "recorded": len(rows), "verified_live": len(live), "by_status": dict(by_status), "unchecked": by_status.get("unchecked", 0),
        "referring_domains": len(domains), "followed": follow, "nofollow_or_ugc_sponsored": len(live) - follow,
        "top_domains": [{"domain": d, "links": n} for d, n in domains.most_common(10)],
        "anchor_distribution": [{"anchor": a, "links": n, "share": round(n / total_anchor, 3)} for a, n in anchors.most_common(10)],
        "destination_pages": [{"url": u, "links": n} for u, n in dests.most_common(10)],
        "single_domain_share": round(domains.most_common(1)[0][1] / len(live), 3) if live else None,
        "lost": [{"source_url": b.source_url, "lost_at": b.lost_at.isoformat() if b.lost_at else None} for b in rows if b.status == "link_removed"][:25],
    }
