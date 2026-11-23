"""Technical checks beyond the crawler's rule engine, each with evidence and a status (pass / warn / fail / not_tested).
Fetches go through safe_fetch (public hosts only, redirect-by-redirect SSRF checks, size and time limits) and are bounded to a handful
of requests per run. Security-header checks are hygiene signals, not ranking factors, and are labelled so.

Technical Health Score `technical-health-v1`: pass = 100, warn = 50, fail = 0 per check, equal weights, tested checks only; checks that
could not be tested are left out (never zero) and lower the coverage figure."""

from __future__ import annotations

from typing import Callable
from urllib.parse import urlsplit, urlunsplit

from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from app.crawler.fetch import DEFAULT_USER_AGENT, FetchError, FetchResult, safe_fetch
from app.intelligence.common import store
from app.keywords.seed_generation import _latest_snapshots
from app.models.website import Website

VERSION = "technical-health-v1"
REQUIRED_PROPS = {
    "organization": ["name"], "localbusiness": ["name", "address"], "medicalbusiness": ["name", "address"], "physiotherapy": ["name", "address"],
    "article": ["headline"], "blogposting": ["headline"], "product": ["name"], "faqpage": ["mainEntity"], "breadcrumblist": ["itemListElement"],
    "website": ["url"], "person": ["name"], "service": ["name"],
}
Fetcher = Callable[[str], FetchResult]


def check(key, label, status, detail, evidence=None, group="technical"):
    return {"key": key, "label": label, "status": status, "detail": detail, "evidence": evidence, "group": group}


def validate_schema(snapshots) -> list[dict]:
    """Required-property check per schema.org type found in the stored JSON-LD (a subset of Google's documented requirements)."""
    out = []
    for url, s in snapshots:
        problems, types = [], []
        def walk(node):
            if isinstance(node, dict):
                t = node.get("@type")
                for x in ([t] if isinstance(t, str) else t or []):
                    if not isinstance(x, str):
                        continue
                    types.append(x)
                    for prop in REQUIRED_PROPS.get(x.lower(), []):
                        if not node.get(prop):
                            problems.append(f"{x} is missing '{prop}'")
                for v in node.values():
                    walk(v)
            elif isinstance(node, list):
                for v in node:
                    walk(v)
        for b in s.schema_json or []:
            if b.get("parse_error"):
                problems.append("JSON-LD could not be parsed")
            walk(b.get("parsed"))
        if types or problems:
            out.append({"url": url, "types": sorted(set(types)), "problems": sorted(set(problems))})
    return out


def _variants(canonical: str) -> list[tuple[str, str]]:
    p = urlsplit(canonical)
    host = p.hostname or ""
    bare = host[4:] if host.startswith("www.") else host
    other = bare if host.startswith("www.") else f"www.{bare}"
    return [("http version", urlunsplit(("http", host, "/", "", ""))), ("alternate host (" + ("non-www" if host.startswith("www.") else "www") + ")", urlunsplit((p.scheme, other, "/", "", "")))]


def analyze(db: Session, website: Website, *, fetcher: Fetcher | None = None, save: bool = True) -> dict:
    fetch = fetcher or (lambda u: safe_fetch(u, user_agent=DEFAULT_USER_AGENT))
    checks: list[dict] = []
    home_url = website.canonical_url
    home = None
    try:
        home = fetch(home_url)
    except Exception as exc:
        checks.append(check("homepage_fetch", "Homepage reachable", "fail", f"Could not fetch the homepage: {exc}", home_url))
    if home is not None:
        checks.append(check("homepage_fetch", "Homepage reachable", "pass" if home.status_code < 400 else "fail", f"HTTP {home.status_code}", home.final_url))
        h = {k.lower(): v for k, v in home.headers.items()}
        soup = BeautifulSoup(home.body or "", "html.parser")
        lang = (soup.html.get("lang") if soup.html else None)
        checks.append(check("html_lang", "Page language declared (html lang)", "pass" if lang else "warn", f"lang=\"{lang}\"" if lang else "No lang attribute on <html>.", home.final_url))
        hrefl = [l.get("hreflang") for l in soup.find_all("link", attrs={"rel": "alternate"}) if l.get("hreflang")]
        if hrefl:
            self_ref = any(l.get("href", "").rstrip("/") == home.final_url.rstrip("/") for l in soup.find_all("link", attrs={"rel": "alternate"}) if l.get("hreflang"))
            checks.append(check("hreflang", "hreflang annotations", "pass" if self_ref else "warn", f"{len(hrefl)} alternate language link(s): {', '.join(sorted(set(hrefl))[:6])}." + ("" if self_ref else " No self-referencing entry."), home.final_url))
        else:
            checks.append(check("hreflang", "hreflang annotations", "not_tested", "None found. Only needed if the site has language or country versions.", home.final_url))
        og = {m.get("property") for m in soup.find_all("meta") if (m.get("property") or "").startswith("og:")}
        missing_og = {"og:title", "og:description", "og:image"} - og
        checks.append(check("open_graph", "Open Graph tags (social previews)", "pass" if not missing_og else "warn", "All of og:title, og:description, og:image present." if not missing_og else f"Missing: {', '.join(sorted(missing_og))}.", home.final_url))
        tw = soup.find("meta", attrs={"name": "twitter:card"})
        checks.append(check("twitter_card", "Twitter/X card", "pass" if tw else "warn", "twitter:card present." if tw else "No twitter:card tag.", home.final_url))
        icon = soup.find("link", rel=lambda r: r and "icon" in " ".join(r if isinstance(r, list) else [r]).lower())
        checks.append(check("favicon", "Favicon declared", "pass" if icon else "warn", "Favicon link found." if icon else "No favicon link in the page head.", home.final_url))
        if urlsplit(home.final_url).scheme == "https":
            for hdr, label in (("strict-transport-security", "HSTS"), ("x-content-type-options", "X-Content-Type-Options"), ("referrer-policy", "Referrer-Policy")):
                checks.append(check(f"hdr_{hdr}", f"{label} header", "pass" if hdr in h else "warn", "Present." if hdr in h else "Not sent. Hygiene signal, not a ranking factor.", home.final_url, "security_hygiene"))
            framing = "x-frame-options" in h or "frame-ancestors" in h.get("content-security-policy", "")
            checks.append(check("hdr_framing", "Clickjacking protection (X-Frame-Options / CSP frame-ancestors)", "pass" if framing else "warn", "Present." if framing else "Not sent. Hygiene signal, not a ranking factor.", home.final_url, "security_hygiene"))
        else:
            checks.append(check("https", "Homepage served over HTTPS", "fail", f"Final URL is {home.final_url}", home.final_url))
        chain = len(home.redirect_chain or [])
        checks.append(check("homepage_redirects", "Homepage redirect chain", "pass" if chain <= 1 else "warn" if chain == 2 else "fail", f"{chain} redirect hop(s) to reach the homepage.", home_url))
    for label, url in _variants(home_url):
        try:
            r = fetch(url)
            same = urlsplit(r.final_url).netloc == urlsplit(home_url).netloc and urlsplit(r.final_url).scheme == urlsplit(home_url).scheme
            checks.append(check(f"canonical_host_{label.split()[0]}", f"{label[0].upper()+label[1:]} redirects to the canonical address", "pass" if same else "fail",
                                f"{url} ends at {r.final_url}." + ("" if same else " Two versions of the site are reachable, which can split signals."), url))
        except Exception as exc:
            checks.append(check(f"canonical_host_{label.split()[0]}", f"{label[0].upper()+label[1:]} redirects to the canonical address", "not_tested", f"Could not fetch {url}: {exc}", url))
    root = f"{urlsplit(home_url).scheme}://{urlsplit(home_url).netloc}"
    for path, key, label in (("/robots.txt", "robots_txt", "robots.txt present"), ("/sitemap.xml", "sitemap_xml", "sitemap.xml present")):
        try:
            r = fetch(root + path)
            checks.append(check(key, label, "pass" if r.status_code == 200 else "warn", f"HTTP {r.status_code}", root + path))
        except Exception as exc:
            checks.append(check(key, label, "not_tested", f"Could not fetch: {exc}", root + path))

    # from the stored crawl
    snaps = _latest_snapshots(db, website.id)
    from app.models.page import Page
    urls = {p.id: p.canonical_url for p in db.query(Page).filter(Page.website_id == website.id).all()}
    chained = [urls[s.page_id] for s in snaps if (s.redirect_count or 0) >= 2 and s.page_id in urls]
    checks.append(check("redirect_chains", "Pages reached through 2+ redirects", "pass" if not chained else "warn", f"{len(chained)} page(s) in the last crawl." if chained else "None in the last crawl.", chained[0] if chained else None))
    schema = validate_schema([(urls[s.page_id], s) for s in snaps if s.page_id in urls])
    bad = [x for x in schema if x["problems"]]
    checks.append(check("structured_data", "Structured data required properties", "not_tested" if not schema else "pass" if not bad else "warn",
                        "No structured data found in the crawl." if not schema else f"{len(schema)} page(s) with markup; {len(bad)} with missing required properties." if bad else f"{len(schema)} page(s) with markup, no missing required properties.",
                        bad[0]["url"] if bad else None, "structured_data"))
    tested = [c for c in checks if c["status"] != "not_tested"]
    pts = {"pass": 100, "warn": 50, "fail": 0}
    score = round(sum(pts[c["status"]] for c in tested) / len(tested), 1) if tested else None
    coverage = round(len(tested) / len(checks), 2) if checks else 0.0
    res = {"available": True, "data_source": "Verified (fetched from your site) + RankPilot calculated", "checks": checks, "structured_data_detail": schema[:50], "tested": len(tested), "not_tested": len(checks) - len(tested),
           "note": "Security headers are hygiene signals, not ranking factors."}
    if save:
        row = store(db, website, "technical", VERSION, score, coverage, res)
        res = {"id": str(row.id), "computed_at": row.computed_at.isoformat(), "formula_version": VERSION, "score": score, "coverage": coverage, **res}
    return res
