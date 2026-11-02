"""Tests for app.crawler.sitemap (RP13-009: recursion/size/URL limits
and rejecting a DOCTYPE that could trigger XML entity-expansion
blowup)."""

from app.crawler import sitemap as sitemap_module
from app.crawler.fetch import FetchResult
from app.crawler.sitemap import MAX_SITEMAP_FILES, MAX_URLS_PER_SITEMAP, discover_sitemap_urls


def _fetch_map(pages: dict[str, str]):
    def fake_safe_fetch(url, **_kwargs):
        body = pages.get(url)
        if body is None:
            return FetchResult(final_url=url, status_code=404, headers={}, body="", redirect_chain=[])
        return FetchResult(final_url=url, status_code=200, headers={}, body=body, redirect_chain=[])

    return fake_safe_fetch


def test_discover_sitemap_urls_parses_a_plain_urlset(monkeypatch):
    sitemap_xml = """<?xml version="1.0"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://example.com/</loc></url>
  <url><loc>https://example.com/about</loc></url>
</urlset>"""
    monkeypatch.setattr(
        sitemap_module, "safe_fetch", _fetch_map({"https://example.com/sitemap.xml": sitemap_xml})
    )

    urls = discover_sitemap_urls("https://example.com/", [], user_agent="RankPilotBot/0.1")
    assert urls == ["https://example.com/", "https://example.com/about"]


def test_discover_sitemap_urls_follows_one_level_of_sitemapindex(monkeypatch):
    index_xml = """<?xml version="1.0"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://example.com/sitemap-a.xml</loc></sitemap>
</sitemapindex>"""
    child_xml = """<?xml version="1.0"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://example.com/page-a</loc></url>
</urlset>"""
    monkeypatch.setattr(
        sitemap_module,
        "safe_fetch",
        _fetch_map(
            {
                "https://example.com/sitemap.xml": index_xml,
                "https://example.com/sitemap-a.xml": child_xml,
            }
        ),
    )

    urls = discover_sitemap_urls("https://example.com/", [], user_agent="RankPilotBot/0.1")
    assert urls == ["https://example.com/page-a"]


def test_discover_sitemap_urls_bounds_nested_sitemap_count(monkeypatch):
    # An index listing far more nested sitemaps than MAX_SITEMAP_FILES.
    nested_entries = "".join(
        f"<sitemap><loc>https://example.com/s{i}.xml</loc></sitemap>" for i in range(50)
    )
    index_xml = f"""<?xml version="1.0"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{nested_entries}</sitemapindex>"""

    fetched_urls = []

    def fake_safe_fetch(url, **_kwargs):
        fetched_urls.append(url)
        if url == "https://example.com/sitemap.xml":
            return FetchResult(final_url=url, status_code=200, headers={}, body=index_xml, redirect_chain=[])
        return FetchResult(
            final_url=url,
            status_code=200,
            headers={},
            body='<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            f'<url><loc>{url}/page</loc></url></urlset>',
            redirect_chain=[],
        )

    monkeypatch.setattr(sitemap_module, "safe_fetch", fake_safe_fetch)

    discover_sitemap_urls("https://example.com/", [], user_agent="RankPilotBot/0.1")
    # One fetch for the index itself, plus at most MAX_SITEMAP_FILES nested ones.
    assert len(fetched_urls) <= MAX_SITEMAP_FILES + 1


def test_discover_sitemap_urls_bounds_urls_per_sitemap():
    urls_block = "".join(f"<url><loc>https://example.com/p{i}</loc></url>" for i in range(MAX_URLS_PER_SITEMAP + 500))
    sitemap_xml = (
        '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"{urls_block}</urlset>"
    )
    page_urls, nested = sitemap_module._parse_sitemap_xml(sitemap_xml)
    assert len(page_urls) == MAX_URLS_PER_SITEMAP
    assert nested == []


def test_parse_sitemap_xml_rejects_a_doctype_to_prevent_entity_expansion_blowup():
    hostile_xml = """<?xml version="1.0"?>
<!DOCTYPE urlset [
  <!ENTITY lol "lol">
  <!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">
]>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>&lol2;</loc></url>
</urlset>"""
    page_urls, nested = sitemap_module._parse_sitemap_xml(hostile_xml)
    assert page_urls == []
    assert nested == []


def test_parse_sitemap_xml_handles_malformed_xml_gracefully():
    page_urls, nested = sitemap_module._parse_sitemap_xml("<not valid xml")
    assert page_urls == []
    assert nested == []
