import pytest

from app.crawler import render


def test_looks_js_rendered_positive_on_low_word_count_with_spa_marker():
    html = '<html><body><div id="root"></div></body></html>'
    assert render.looks_js_rendered(raw_html=html, word_count=5) is True


def test_looks_js_rendered_negative_when_word_count_is_already_high():
    html = '<html><body><div id="root"></div></body></html>'
    assert render.looks_js_rendered(raw_html=html, word_count=200) is False


def test_looks_js_rendered_negative_without_a_spa_marker():
    html = "<html><body><p>A short page with no framework marker</p></body></html>"
    assert render.looks_js_rendered(raw_html=html, word_count=5) is False


@pytest.mark.parametrize(
    "marker", ['id="root"', 'id="__next"', 'id="app"', "ng-version", "data-reactroot"]
)
def test_looks_js_rendered_recognizes_each_known_framework_marker(marker):
    html = f"<html><body><div {marker}></div></body></html>"
    assert render.looks_js_rendered(raw_html=html, word_count=0) is True


def test_render_page_rejects_an_unsafe_url_without_launching_a_browser(monkeypatch):
    launched = {"called": False}

    class _ShouldNotBeCalled:
        def __enter__(self):
            launched["called"] = True
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(render, "sync_playwright", lambda: _ShouldNotBeCalled())

    with pytest.raises(render.RenderError, match="unsafe_url"):
        render.render_page("http://127.0.0.1/admin")

    assert launched["called"] is False


def test_render_page_wraps_a_playwright_failure_as_render_error(monkeypatch):
    from playwright.sync_api import Error as PlaywrightError

    class _FailingBrowser:
        def new_page(self):
            raise PlaywrightError("navigation timeout")

        def close(self):
            pass

    class _FailingChromium:
        def launch(self, **kwargs):
            return _FailingBrowser()

    class _FailingPlaywright:
        def __enter__(self):
            return type("P", (), {"chromium": _FailingChromium()})()

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(render, "sync_playwright", lambda: _FailingPlaywright())
    monkeypatch.setattr(render, "validate_public_url", lambda url: None)

    with pytest.raises(render.RenderError, match="Rendering failed"):
        render.render_page("https://example.com/")


def test_render_page_returns_the_final_dom_content_on_success(monkeypatch):
    class _FakePage:
        def goto(self, url, timeout=None, wait_until=None):
            pass

        def content(self):
            return "<html><body>Rendered content</body></html>"

    class _FakeBrowser:
        def new_page(self):
            return _FakePage()

        def close(self):
            pass

    class _FakeChromium:
        def launch(self, **kwargs):
            return _FakeBrowser()

    class _FakePlaywright:
        def __enter__(self):
            return type("P", (), {"chromium": _FakeChromium()})()

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(render, "sync_playwright", lambda: _FakePlaywright())
    monkeypatch.setattr(render, "validate_public_url", lambda url: None)

    result = render.render_page("https://example.com/")
    assert result.html == "<html><body>Rendered content</body></html>"
