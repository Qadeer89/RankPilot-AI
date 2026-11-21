"""A small fake website used to test the crawler and rule engine
deterministically, with no real network or DNS resolution.
"""

from __future__ import annotations

from app.crawler.fetch import FetchError, FetchResult

ROBOTS_TXT = "User-agent: *\nDisallow: /blocked/\nSitemap: https://example.com/sitemap.xml\n"

SITEMAP_XML = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://example.com/</loc></url>
  <url><loc>https://example.com/about</loc></url>
  <url><loc>https://example.com/orphan</loc></url>
  <url><loc>https://example.com/broken</loc></url>
</urlset>
"""

HOME_HTML = """
<html><head>
<title>Home - Example</title>
<meta name="description" content="A perfectly reasonable description of the home page.">
<link rel="canonical" href="https://example.com/">
</head><body>
<h1>Welcome</h1>
<a href="/about">About</a>
<a href="/missing-page">Missing</a>
<a href="/blocked/secret">Secret</a>
<img src="/broken" alt="References a URL this site crawled and knows returned an error">
<a href="https://partner.example/resource">A working partner link</a>
<a href="https://dead-partner.example/gone" rel="nofollow sponsored">A dead sponsored link</a>
<a href="https://redirecting-partner.example/old">A partner link that redirects</a>
</body></html>
"""

ABOUT_HTML = """
<html><head>
<title>Home - Example</title>
<script type="application/ld+json">{not valid json}</script>
<link rel="canonical" href="https://example.com/">
<link rel="prev" href="/">
<link rel="next" href="/missing-page">
</head><body>
<a href="/">Home</a>
<h3>Our team (no h1 or h2 before this)</h3>
<img src="/team.jpg">
<img src="" alt="this one has no src at all">
<img src="/decorative.png" alt="">
<img src="/photo.jpg" alt="IMG_1234" width="400" height="300">
<img src="/founder.jpg" alt="Founder presenting at a product launch event" width="800" height="600">
</body></html>
"""

ORPHAN_HTML = """
<html><head>
<title>Orphan Page</title>
<meta name="description" content="This page is only reachable via the sitemap.">
</head><body>
<h1>Orphan</h1>
</body></html>
"""

NOT_FOUND_HTML = "<html><body>Not Found</body></html>"

PAGES: dict[str, dict] = {
    "https://example.com/robots.txt": {"status_code": 200, "body": ROBOTS_TXT},
    "https://example.com/sitemap.xml": {"status_code": 200, "body": SITEMAP_XML},
    "https://example.com/": {"status_code": 200, "body": HOME_HTML},
    "https://example.com/about": {"status_code": 200, "body": ABOUT_HTML},
    "https://example.com/orphan": {"status_code": 200, "body": ORPHAN_HTML},
    "https://example.com/broken": {"status_code": 404, "body": NOT_FOUND_HTML},
    "https://example.com/missing-page": {"status_code": 404, "body": NOT_FOUND_HTML},
    "https://partner.example/resource": {"status_code": 200, "body": "<html><body>ok</body></html>"},
    "https://redirecting-partner.example/old": {
        "status_code": 200,
        "body": "<html><body>moved</body></html>",
        "redirect_chain": ["https://redirecting-partner.example/old"],
    },
    # https://dead-partner.example/gone is deliberately NOT registered --
    # fake_safe_fetch raises FetchError for it, simulating a genuinely
    # unreachable external link.
}


def fake_safe_fetch(url: str, **_kwargs) -> FetchResult:
    entry = PAGES.get(url)
    if entry is None:
        raise FetchError(f"unsafe_url: Could not resolve host '{url}' (no fixture registered).")
    return FetchResult(
        final_url=url,
        status_code=entry["status_code"],
        headers={},
        body=entry["body"],
        redirect_chain=entry.get("redirect_chain", []),
    )


def patch_crawler_network(monkeypatch) -> None:
    """Redirect every module that calls `safe_fetch` to the fixture above.

    Each module imported `safe_fetch` by name, so the attribute has to be
    patched on every one of them individually.
    """
    import app.crawler.orchestrator as orchestrator_module
    import app.crawler.robots as robots_module
    import app.crawler.sitemap as sitemap_module

    monkeypatch.setattr(robots_module, "safe_fetch", fake_safe_fetch)
    monkeypatch.setattr(sitemap_module, "safe_fetch", fake_safe_fetch)
    monkeypatch.setattr(orchestrator_module, "safe_fetch", fake_safe_fetch)
    # RP13-008's per-host crawl delay is real-time and would otherwise add
    # 0.5s+ per fetched page to every crawler test.
    monkeypatch.setattr(orchestrator_module.time, "sleep", lambda _seconds: None)
