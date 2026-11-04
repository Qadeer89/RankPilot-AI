from app.crawler.extract import extract_page


def test_cloudflare_email_obfuscation_link_is_not_treated_as_an_internal_page():
    """Cloudflare's email-obfuscation feature rewrites a mailto: href
    server-side into /cdn-cgi/l/email-protection#<hash> before the raw
    HTML ever reaches the crawler -- the mailto: prefix check never sees
    it, so without this exclusion it looked like a real same-site page,
    got crawled, and reliably errored (false-positive BROKEN_INTERNAL_LINK
    / HTTP_ERROR_STATUS findings on every page that has an "email us" link).
    """
    html = """
    <html><head><title>Contact</title></head><body>
    <a href="/cdn-cgi/l/email-protection#7e1a1d1c1b1a1e1a1d1a1b1a1f1d">Email us</a>
    <a href="/about">About</a>
    </body></html>
    """
    extraction = extract_page(html, base_url="https://example.com/contact", site_hostname="example.com")
    assert extraction.internal_links == ["https://example.com/about"]


def test_mailto_and_tel_and_javascript_links_are_still_excluded():
    html = """
    <html><head><title>Contact</title></head><body>
    <a href="mailto:hello@example.com">Email</a>
    <a href="tel:+15551234567">Call</a>
    <a href="javascript:void(0)">Nothing</a>
    <a href="/about">About</a>
    </body></html>
    """
    extraction = extract_page(html, base_url="https://example.com/contact", site_hostname="example.com")
    assert extraction.internal_links == ["https://example.com/about"]
