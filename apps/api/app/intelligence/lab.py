"""Local lab measurement with RankPilot's own headless browser (Playwright/Chromium, already used for JS rendering).

This is a lab measurement from the RankPilot server, not field data from real visitors and not a Lighthouse score; it is labelled as such.
It records time to first byte, DOM content loaded, load event, request count, transferred bytes and the largest-contentful-paint time
reported by the browser, on a mobile-sized viewport with a fresh cache. Results vary with server load and network, so compare runs
taken the same way over time and treat a single run as indicative only. If the `lighthouse` CLI is installed on the server
(LIGHTHOUSE_BIN or on PATH) it is used for a full Lighthouse lab score; otherwise Lighthouse is reported as Not tested.
Google's free PageSpeed Insights API (field + lab data) remains the primary source and is stored separately (PerformanceMetric)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from urllib.parse import urlsplit

from sqlalchemy.orm import Session

from app.core.url_safety import UnsafeUrlError, validate_public_url
from app.intelligence.common import store
from app.models.website import Website

VERSION = "local-lab-v1"
MOBILE = {"viewport": {"width": 390, "height": 844}, "user_agent": "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 Chrome/120 Mobile Safari/537.36", "device_scale_factor": 2}


def measure_page(url: str, *, timeout_ms: int = 30000) -> dict:
    """One cold-cache load. No validation here; callers validate. Raises on browser failure."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        from app.crawler.render import CHROMIUM_EXECUTABLE_PATH

        kwargs = {"headless": True, "args": ["--no-sandbox"]}
        if CHROMIUM_EXECUTABLE_PATH is not None:
            kwargs["executable_path"] = CHROMIUM_EXECUTABLE_PATH
        browser = pw.chromium.launch(**kwargs)
        try:
            ctx = browser.new_context(**MOBILE)
            page = ctx.new_page()
            sizes = {"requests": 0, "bytes": 0}
            def on_response(resp):
                sizes["requests"] += 1
                try:
                    sizes["bytes"] += int(resp.headers.get("content-length") or 0)
                except ValueError:
                    pass
            page.on("response", on_response)
            page.add_init_script("window.__lcp=0;new PerformanceObserver(l=>{for(const e of l.getEntries())window.__lcp=e.startTime}).observe({type:'largest-contentful-paint',buffered:true})")
            resp = page.goto(url, wait_until="load", timeout=timeout_ms)
            page.wait_for_timeout(500)
            nav = page.evaluate("(()=>{const n=performance.getEntriesByType('navigation')[0];return {ttfb:n.responseStart,dcl:n.domContentLoadedEventEnd,load:n.loadEventEnd}})()")
            lcp = page.evaluate("window.__lcp")
            return {"status_code": resp.status if resp else None, "ttfb_ms": round(nav["ttfb"]), "dom_content_loaded_ms": round(nav["dcl"]), "load_ms": round(nav["load"]),
                    "lcp_ms": round(lcp) if lcp else None, "requests": sizes["requests"], "transferred_bytes_reported": sizes["bytes"]}
        finally:
            browser.close()


def lighthouse(url: str) -> dict:
    exe = os.environ.get("LIGHTHOUSE_BIN") or shutil.which("lighthouse")
    if not exe:
        return {"status": "not_tested", "reason": "The Lighthouse CLI is not installed on this server. Install it (npm i -g lighthouse) or set LIGHTHOUSE_BIN to enable it. PageSpeed Insights data is still available."}
    try:
        out = subprocess.run([exe, url, "--quiet", "--output=json", "--only-categories=performance,seo,accessibility,best-practices", "--chrome-flags=--headless --no-sandbox"],
                             capture_output=True, text=True, timeout=120, check=True)
        cats = json.loads(out.stdout)["categories"]
        return {"status": "tested", "scores": {k: round((v["score"] or 0) * 100) for k, v in cats.items()}}
    except Exception as exc:
        return {"status": "error", "reason": f"Lighthouse failed: {type(exc).__name__}"}


def run(db: Session, website: Website, url: str | None = None, *, measure=measure_page, lh=lighthouse, save: bool = True) -> dict:
    target = url or website.canonical_url
    own = (urlsplit(website.canonical_url).hostname or "").lower().removeprefix("www.")
    if (urlsplit(target).hostname or "").lower().removeprefix("www.") != own:
        raise UnsafeUrlError("Only pages on this project's own website can be measured.")
    validate_public_url(target)
    try:
        m = {"status": "tested", **measure(target)}
    except Exception as exc:
        m = {"status": "error", "reason": f"The headless browser could not load the page: {type(exc).__name__}"}
    res = {"available": m["status"] == "tested", "data_source": "Lab measurement (RankPilot local browser). Not field data, not Lighthouse.", "url": target, "device": "mobile viewport, cold cache", "measurement": m,
           "lighthouse": lh(target),
           "notes": ["Single runs vary with server load and network; compare runs taken the same way over time.", "Real-visitor (field) data comes from PageSpeed Insights / CrUX and may not exist for low-traffic pages."]}
    if save and m["status"] == "tested":
        row = store(db, website, "lab_performance", VERSION, None, None, res)
        res = {"id": str(row.id), "computed_at": row.computed_at.isoformat(), "formula_version": VERSION, **res}
    return res
