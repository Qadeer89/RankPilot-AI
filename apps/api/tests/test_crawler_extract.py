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


def test_word_count_excludes_script_and_style_text():
    html = """
    <html><head><title>Page</title>
    <style>.hidden { display: none; }</style>
    </head><body>
    <script>var analyticsId = "UA-123-456"; trackPageview();</script>
    <p>Four real words here</p>
    </body></html>
    """
    extraction = extract_page(html, base_url="https://example.com/", site_hostname="example.com")
    assert extraction.word_count == 4


def test_external_links_are_tracked_separately_from_internal_links():
    html = """
    <html><head><title>Links</title></head><body>
    <a href="/about">About</a>
    <a href="https://other-site.com/page" rel="nofollow">Other site</a>
    <a href="https://sponsor.example/deal" rel="sponsored noopener">Sponsored deal</a>
    <a href="https://ugc.example/comment" rel="ugc">A comment link</a>
    <a href="https://plain.example/blog">Plain external link</a>
    </body></html>
    """
    extraction = extract_page(html, base_url="https://example.com/", site_hostname="example.com")
    assert extraction.internal_links == ["https://example.com/about"]

    by_url = {link.url: link for link in extraction.external_links}
    assert set(by_url) == {
        "https://other-site.com/page",
        "https://sponsor.example/deal",
        "https://ugc.example/comment",
        "https://plain.example/blog",
    }
    assert by_url["https://other-site.com/page"].is_nofollow is True
    assert by_url["https://sponsor.example/deal"].is_sponsored is True
    assert by_url["https://ugc.example/comment"].is_ugc is True
    plain = by_url["https://plain.example/blog"]
    assert plain.is_nofollow is False and plain.is_sponsored is False and plain.is_ugc is False


def test_cloudflare_email_obfuscation_link_is_not_misclassified_as_external():
    """Regression guard for the external-link audit: a same-hostname link
    _normalize_link deliberately excludes from internal_links (the
    cdn-cgi email-obfuscation rewrite) must not fall through into
    external_links either -- it's neither, it's noise to be dropped.
    """
    html = """
    <html><head><title>Contact</title></head><body>
    <a href="/cdn-cgi/l/email-protection#7e1a1d1c1b1a1e1a1d1a1b1a1f1d">Email us</a>
    </body></html>
    """
    extraction = extract_page(html, base_url="https://example.com/contact", site_hostname="example.com")
    assert extraction.internal_links == []
    assert extraction.external_links == []


def test_external_links_are_deduplicated():
    html = """
    <html><head><title>Links</title></head><body>
    <a href="https://other-site.com/page">First mention</a>
    <a href="https://other-site.com/page">Second mention</a>
    </body></html>
    """
    extraction = extract_page(html, base_url="https://example.com/", site_hostname="example.com")
    assert len(extraction.external_links) == 1


def test_content_fingerprint_matches_for_identical_body_text_despite_different_scripts():
    html_a = """
    <html><head><title>A</title></head><body>
    <script>var a = 1;</script>
    <p>Exactly the same body copy on both pages.</p>
    </body></html>
    """
    html_b = """
    <html><head><title>B</title></head><body>
    <script>var b = 2; doSomethingElse();</script>
    <p>Exactly the same body copy on both pages.</p>
    </body></html>
    """
    extraction_a = extract_page(html_a, base_url="https://example.com/a", site_hostname="example.com")
    extraction_b = extract_page(html_b, base_url="https://example.com/b", site_hostname="example.com")
    assert extraction_a.content_fingerprint == extraction_b.content_fingerprint
