"""SSRF-safe HTTP fetching for the crawler (RP-0302, SECURITY_SPECIFICATION.md #4).

Every hop of every redirect is independently re-validated with
`validate_public_url` before it is followed — httpx's own `follow_redirects`
is deliberately not used, because it would fetch the Location header without
re-checking it against SSRF rules first.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.core.url_safety import UnsafeUrlError, validate_public_url

MAX_REDIRECTS = 5
MAX_RESPONSE_BYTES = 5 * 1024 * 1024  # 5 MB
DEFAULT_TIMEOUT_SECONDS = 10.0
DEFAULT_USER_AGENT = "RankPilotBot/0.1 (+https://rankpilot.ai/bot)"


class FetchError(Exception):
    """Raised when a URL cannot be safely or successfully fetched."""


@dataclass(frozen=True)
class FetchResult:
    final_url: str
    status_code: int
    headers: dict[str, str]
    body: str
    redirect_chain: list[str]


def _read_bounded_text(response: httpx.Response) -> str:
    content_length = response.headers.get("content-length")
    if content_length is not None and int(content_length) > MAX_RESPONSE_BYTES:
        raise FetchError(f"Response too large ({content_length} bytes).")

    total = 0
    chunks: list[bytes] = []
    for chunk in response.iter_bytes():
        total += len(chunk)
        if total > MAX_RESPONSE_BYTES:
            raise FetchError("Response exceeded the maximum allowed size while streaming.")
        chunks.append(chunk)
    return b"".join(chunks).decode(response.encoding or "utf-8", errors="replace")


def safe_fetch(
    url: str,
    *,
    user_agent: str = DEFAULT_USER_AGENT,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    max_redirects: int = MAX_REDIRECTS,
) -> FetchResult:
    """Fetch `url`, manually re-validating every redirect hop for SSRF safety."""
    redirect_chain: list[str] = []
    current_url = url

    for _ in range(max_redirects + 1):
        try:
            safe_url = validate_public_url(current_url)
        except UnsafeUrlError as exc:
            raise FetchError(f"unsafe_url: {exc}") from exc

        try:
            with httpx.Client(timeout=timeout, follow_redirects=False) as client:
                response = client.get(safe_url.normalized_url, headers={"User-Agent": user_agent})
        except httpx.HTTPError as exc:
            raise FetchError(f"Request failed: {exc}") from exc

        if response.is_redirect:
            location = response.headers.get("location")
            if not location:
                raise FetchError("Redirect response had no Location header.")
            redirect_chain.append(safe_url.normalized_url)
            current_url = httpx.URL(safe_url.normalized_url).join(location).human_repr()
            continue

        body = _read_bounded_text(response)
        return FetchResult(
            final_url=safe_url.normalized_url,
            status_code=response.status_code,
            headers=dict(response.headers),
            body=body,
            redirect_chain=redirect_chain,
        )

    raise FetchError(f"Exceeded max redirects ({max_redirects}) fetching {url}.")
