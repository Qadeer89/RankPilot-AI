"""Edge cases of the public competitor crawler, against a scripted fake
`safe_fetch`/robots layer (no network). Real-site behaviour is checked by
scripts/validate_growth_engine.py. SSRF blocking itself lives in
tests/test_url_safety*.py and is exercised by the real script too.
"""

from types import SimpleNamespace

import pytest

from app.competitors import crawler
from app.crawler.fetch import FetchError, FetchResult
from app.crawler.robots import RobotsPolicy

HTML = "<html><head><title>{t}</title></head><body><h1>{t}</h1><p>{body}</p>{links}</body></html>"


def page(title="Home", body="word " * 80, links="", status=200, headers=None, final_url="https://rival.example/"):
    return FetchResult(
        final_url=final_url,
        status_code=status,
        headers={"content-type": "text/html; charset=utf-8", **(headers or {})},
        body=HTML.format(t=title, body=body, links=links),
        redirect_chain=[],
    )


@pytest.fixture
def env(monkeypatch):
    state = SimpleNamespace(sleeps=[], calls=[], clock=0.0, robots={}, responses={})

    def fake_sleep(seconds):
        state.sleeps.append(seconds)
        state.clock += seconds

    def fake_robots(url, *, user_agent):
        host = url.split("/")[2]
        policy = state.robots.get(host)
        if isinstance(policy, Exception):
            raise policy
        return policy

    def fake_fetch(url, **kwargs):
        state.calls.append(url)
        queue = state.responses.get(url)
        if queue is None:
            raise AssertionError(f"unexpected fetch {url}")
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(crawler, "_sleep", fake_sleep)
    monkeypatch.setattr(crawler, "_monotonic", lambda: state.clock)
    monkeypatch.setattr(crawler, "fetch_robots_policy", fake_robots)
    monkeypatch.setattr(crawler, "safe_fetch", fake_fetch)
    return state


def robots(disallow=None, delay=None):
    return RobotsPolicy(
        sitemap_urls=[],
        _parser=SimpleNamespace(
            can_fetch=lambda url, ua: not (disallow and disallow in url), crawl_delay=lambda ua: delay
        ),
    )


def test_http_error_pages_are_not_treated_as_content(env):
    env.responses["https://rival.example"] = [page(title="404 Not Found", status=404)]
    results = crawler.fetch_competitor_pages("rival.example")
    assert [(r.title, r.error) for r in results] == [(None, "HTTP 404")]


def test_non_html_content_is_rejected(env):
    env.responses["https://rival.example"] = [page(headers={"content-type": "application/pdf"})]
    (result,) = crawler.fetch_competitor_pages("rival.example")
    assert result.error.startswith("Not an HTML page") and result.title is None


def test_javascript_shell_is_reported_not_guessed(env):
    shell = FetchResult(
        final_url="https://rival.example/", status_code=200, headers={"content-type": "text/html"},
        body='<html><head></head><body><div id="root"></div><script src="/app.js"></script></body></html>',
        redirect_chain=[],
    )
    env.responses["https://rival.example"] = [shell]
    (result,) = crawler.fetch_competitor_pages("rival.example")
    assert "JavaScript" in result.error and result.headings == {}


def test_robots_disallowed_subpage_is_reported_and_never_fetched(env):
    env.robots["rival.example"] = robots(disallow="/private")
    env.responses["https://rival.example"] = [page(links='<a href="/private/x">x</a><a href="/about">a</a>')]
    env.responses["https://rival.example/about"] = [page(title="About", final_url="https://rival.example/about")]

    results = crawler.fetch_competitor_pages("rival.example")

    by_url = {r.url: r for r in results}
    assert by_url["https://rival.example/private/x"].error == "Blocked by this site's robots.txt."
    assert "https://rival.example/private/x" not in env.calls
    assert by_url["https://rival.example/about"].title == "About"


def test_missing_robots_txt_allows_crawling(env):
    env.robots["rival.example"] = FetchError("boom")
    env.responses["https://rival.example"] = [page()]
    (result,) = crawler.fetch_competitor_pages("rival.example")
    assert result.error is None


def test_requests_are_throttled_and_crawl_delay_is_honoured_but_capped(env):
    env.robots["rival.example"] = robots(delay=3)
    env.responses["https://rival.example"] = [page(links='<a href="/a">a</a><a href="/b">b</a>')]
    env.responses["https://rival.example/a"] = [page(title="A", final_url="https://rival.example/a")]
    env.responses["https://rival.example/b"] = [page(title="B", final_url="https://rival.example/b")]
    crawler.fetch_competitor_pages("rival.example")
    assert env.sleeps == [3, 3]  # waits between pages, never before the first

    env.sleeps.clear(); env.calls.clear()
    env.robots["rival.example"] = robots(delay=600)
    crawler.fetch_competitor_pages("rival.example")
    assert max(env.sleeps) == crawler.MAX_CRAWL_DELAY_SECONDS

    env.sleeps.clear()
    env.robots["rival.example"] = None
    crawler.fetch_competitor_pages("rival.example")
    assert min(env.sleeps) >= crawler.MIN_REQUEST_DELAY_SECONDS


def test_timeout_is_retried_once_then_succeeds(env):
    env.responses["https://rival.example"] = [FetchError("Request failed: timed out"), page()]
    (result,) = crawler.fetch_competitor_pages("rival.example")
    assert result.error is None and env.calls.count("https://rival.example") == 2
    assert env.sleeps == [crawler.DEFAULT_RETRY_WAIT_SECONDS]


def test_timeout_that_keeps_failing_gives_up_after_one_retry(env):
    env.responses["https://rival.example"] = [FetchError("Request failed: timed out")]
    (result,) = crawler.fetch_competitor_pages("rival.example")
    assert "timed out" in result.error and env.calls.count("https://rival.example") == 2


def test_rate_limited_response_honours_a_capped_retry_after(env):
    env.responses["https://rival.example"] = [page(status=429, headers={"retry-after": "120"}), page()]
    (result,) = crawler.fetch_competitor_pages("rival.example")
    assert result.error is None
    assert env.sleeps == [crawler.MAX_RETRY_WAIT_SECONDS]


def test_server_error_is_retried_once_and_reported(env):
    env.responses["https://rival.example"] = [page(status=503)]
    (result,) = crawler.fetch_competitor_pages("rival.example")
    assert result.error == "HTTP 503" and env.calls.count("https://rival.example") == 2


@pytest.mark.parametrize("message", ["unsafe_url: private address", "Response too large (9999999 bytes).",
                                     "Exceeded max redirects (5) fetching x."])
def test_unsafe_oversize_and_redirect_loops_are_never_retried(env, message):
    env.responses["https://rival.example"] = [FetchError(message)]
    (result,) = crawler.fetch_competitor_pages("rival.example")
    assert result.error == message and env.calls == ["https://rival.example"]


def test_crawl_stops_at_the_page_limit_and_the_time_limit(env):
    links = "".join(f'<a href="/p{i}">p</a>' for i in range(20))
    env.responses["https://rival.example"] = [page(links=links)]
    for i in range(20):
        env.responses[f"https://rival.example/p{i}"] = [page(title=f"P{i}", final_url=f"https://rival.example/p{i}")]
    assert len(crawler.fetch_competitor_pages("rival.example", max_pages=3)) == 3

    env.calls.clear()
    env.clock = 0.0
    real_sleep = env.sleeps

    def jump(seconds):
        env.clock += 100  # every wait burns the whole budget
        real_sleep.append(seconds)

    crawler._sleep = jump  # restored by monkeypatch teardown of the fixture's setattr
    results = crawler.fetch_competitor_pages("rival.example")
    assert results[-1].error.startswith("Stopped after")
    assert len(results) < 5


def test_robots_are_checked_for_the_host_the_redirect_landed_on(env):
    env.robots["rival.example"] = None
    env.robots["www.rival.example"] = robots(disallow="/about")
    env.responses["https://rival.example"] = [
        page(final_url="https://www.rival.example/", links='<a href="https://www.rival.example/about">a</a>')
    ]
    results = crawler.fetch_competitor_pages("rival.example")
    blocked = [r for r in results if r.error and "robots" in r.error]
    assert [r.url for r in blocked] == ["https://www.rival.example/about"]
