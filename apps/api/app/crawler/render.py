"""Headless-browser rendering for JavaScript-heavy pages (RankPilot AI
Phase 4 "Advanced Crawling & Performance Intelligence").

Used selectively, never as the default path: the fast HTTP crawler
(app/crawler/fetch.py) still fetches every page. Rendering is only
attempted when a page's raw HTML looks JS-dependent -- very little
visible text alongside a recognizable SPA framework root marker -- so
a normal content page that merely uses some JavaScript never pays the
cost of spinning up a browser.

SSRF note: unlike safe_fetch, a real browser resolves DNS itself at
connect time, which this module cannot pin to a pre-validated IP the
way httpx can (RP13-007's pinned-connection trick). Re-validating the
URL immediately before navigation narrows, but does not eliminate, the
DNS-rebinding window a dedicated attacker could exploit in the moment
between validation and the browser's own connection. This is a
documented trade-off of using a real browser engine for this one,
selective code path -- not an oversight, and not a weakening of the
fast crawler's own protection, which is unchanged.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

from app.core.url_safety import UnsafeUrlError, validate_public_url

RENDER_TIMEOUT_MS = 15_000

# A pre-provisioned Chromium binary, when one exists at this well-known
# path (true in this project's cloud dev sandbox) -- reused to avoid a
# redundant download. On a host without one (e.g. the production VPS),
# this stays None and Playwright falls back to its own bundled browser
# (installed via `playwright install chromium`, under ~/.cache/ms-playwright).
_SANDBOX_CHROMIUM_PATH = "/opt/pw-browsers/chromium"
CHROMIUM_EXECUTABLE_PATH = _SANDBOX_CHROMIUM_PATH if os.path.exists(_SANDBOX_CHROMIUM_PATH) else None

# A page is a reasonable rendering candidate only when its raw HTML
# strongly suggests client-side rendering: very little visible text
# alongside a recognizable SPA framework root element. These markers
# are deliberately narrow -- real signals a specific framework left in
# the markup, not a guess from JavaScript's mere presence (nearly every
# site has some).
_SPA_ROOT_MARKERS = ('id="root"', 'id="__next"', 'id="app"', "ng-version", "data-reactroot")
MIN_WORD_COUNT_TO_SKIP_RENDERING = 50


class RenderError(Exception):
    """Raised when a page could not be safely or successfully rendered."""


@dataclass(frozen=True)
class RenderResult:
    html: str


def looks_js_rendered(*, raw_html: str, word_count: int) -> bool:
    if word_count >= MIN_WORD_COUNT_TO_SKIP_RENDERING:
        return False
    lowered = raw_html.lower()
    return any(marker in lowered for marker in _SPA_ROOT_MARKERS)


def render_page(url: str, *, timeout_ms: int = RENDER_TIMEOUT_MS) -> RenderResult:
    """Render `url` in a real headless browser and return its final DOM
    content. Raises RenderError on any failure, including an unsafe
    URL -- re-validated here independent of whatever check the caller
    already did, since this is the one crawler code path that can't
    pin the validated IP the way safe_fetch does.
    """
    try:
        validate_public_url(url)
    except UnsafeUrlError as exc:
        raise RenderError(f"unsafe_url: {exc}") from exc

    launch_kwargs = {"headless": True, "args": ["--no-sandbox"]}
    if CHROMIUM_EXECUTABLE_PATH is not None:
        launch_kwargs["executable_path"] = CHROMIUM_EXECUTABLE_PATH

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(**launch_kwargs)
            try:
                page = browser.new_page()
                page.goto(url, timeout=timeout_ms, wait_until="networkidle")
                html = page.content()
            finally:
                browser.close()
    except PlaywrightError as exc:
        raise RenderError(f"Rendering failed for {url}: {exc}") from exc

    return RenderResult(html=html)
