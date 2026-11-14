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


def test_image_extraction_distinguishes_missing_src_decorative_and_dimensions():
    html = """
    <html><head><title>Gallery</title></head><body>
    <img src="/photo.jpg" alt="A dog running on the beach" width="800" height="600">
    <img src="/icon.png" alt="">
    <img src="no-alt.png">
    <img alt="no src at all">
    <img src="  ">
    </body></html>
    """
    extraction = extract_page(html, base_url="https://example.com/gallery", site_hostname="example.com")
    images = extraction.images
    assert len(images) == 5

    photo = images[0]
    assert photo.src == "https://example.com/photo.jpg"
    assert photo.alt_text == "A dog running on the beach"
    assert photo.has_alt is True
    assert photo.is_decorative is False
    assert photo.has_dimensions is True

    decorative = images[1]
    assert decorative.has_alt is True
    assert decorative.alt_text is None
    assert decorative.is_decorative is True

    no_alt = images[2]
    assert no_alt.has_alt is False
    assert no_alt.is_decorative is False

    no_src = images[3]
    assert no_src.src is None

    blank_src = images[4]
    assert blank_src.src is None
