"""WordPress connector: the first general-purpose write connector
(RP-0703, RP-0704, WEBSITE_CONNECTORS.md #3).

Authenticates with a WordPress Application Password (a dedicated,
revocable, least-privilege credential — never the site owner's main
account password). Only `set_title` is a reliable, core-WordPress
operation; `set_meta_description` is best-effort and depends on the site
exposing a compatible REST-visible meta field (e.g. via Yoast SEO),
exactly the kind of "declare supported operations" caveat
WEBSITE_CONNECTORS.md #6 asks for.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

YOAST_META_DESCRIPTION_KEY = "_yoast_wpseo_metadesc"
POST_TYPES_TO_SEARCH = ("pages", "posts")
REQUEST_TIMEOUT_SECONDS = 15.0


class WordPressConnectorError(RuntimeError):
    pass


class UnsupportedOperation(WordPressConnectorError):
    pass


@dataclass(frozen=True)
class WordPressCredentials:
    site_url: str
    username: str
    application_password: str

    @property
    def auth(self) -> tuple[str, str]:
        return (self.username, self.application_password)


def _api_base(site_url: str) -> str:
    parts = urlsplit(site_url)
    return f"{parts.scheme}://{parts.netloc}/wp-json/wp/v2"


def verify_credentials(credentials: WordPressCredentials) -> dict:
    """Confirm the Application Password works and return the WP user it
    authenticates as. Raises WordPressConnectorError on any failure.
    """
    response = httpx.get(
        f"{_api_base(credentials.site_url)}/users/me",
        auth=credentials.auth,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    if response.status_code != 200:
        raise WordPressConnectorError(
            f"Could not verify WordPress credentials: HTTP {response.status_code} {response.text[:200]}"
        )
    return response.json()


def find_post_by_url(credentials: WordPressCredentials, target_url: str) -> tuple[str, int]:
    """Resolve `target_url` to a (post_type, post_id) pair by matching its
    slug against pages, then posts. Raises WordPressConnectorError if no
    match is found in either.
    """
    slug = urlsplit(target_url).path.rstrip("/").rsplit("/", 1)[-1] or ""

    for post_type in POST_TYPES_TO_SEARCH:
        response = httpx.get(
            f"{_api_base(credentials.site_url)}/{post_type}",
            params={"slug": slug},
            auth=credentials.auth,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        if response.status_code == 200:
            results = response.json()
            if results:
                return post_type, results[0]["id"]

    raise WordPressConnectorError(f"No WordPress page or post found matching URL: {target_url}")


def get_resource(credentials: WordPressCredentials, post_type: str, post_id: int) -> dict:
    response = httpx.get(
        f"{_api_base(credentials.site_url)}/{post_type}/{post_id}",
        auth=credentials.auth,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    if response.status_code != 200:
        raise WordPressConnectorError(
            f"Could not fetch {post_type}/{post_id}: HTTP {response.status_code} {response.text[:200]}"
        )
    return response.json()


def current_title(resource: dict) -> str:
    return resource.get("title", {}).get("rendered", "")


def current_meta_description(resource: dict) -> str:
    return resource.get("meta", {}).get(YOAST_META_DESCRIPTION_KEY, "")


def update_title(credentials: WordPressCredentials, post_type: str, post_id: int, new_title: str) -> dict:
    response = httpx.post(
        f"{_api_base(credentials.site_url)}/{post_type}/{post_id}",
        auth=credentials.auth,
        json={"title": new_title},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    if response.status_code != 200:
        raise WordPressConnectorError(
            f"Failed to update title on {post_type}/{post_id}: HTTP {response.status_code} {response.text[:200]}"
        )
    return response.json()


def update_meta_description(
    credentials: WordPressCredentials, post_type: str, post_id: int, new_description: str
) -> dict:
    response = httpx.post(
        f"{_api_base(credentials.site_url)}/{post_type}/{post_id}",
        auth=credentials.auth,
        json={"meta": {YOAST_META_DESCRIPTION_KEY: new_description}},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    if response.status_code == 400:
        raise UnsupportedOperation(
            "This WordPress site does not expose a REST-writable meta description field "
            "(expected a Yoast SEO-compatible meta key)."
        )
    if response.status_code != 200:
        raise WordPressConnectorError(
            f"Failed to update meta description on {post_type}/{post_id}: "
            f"HTTP {response.status_code} {response.text[:200]}"
        )
    body = response.json()
    if current_meta_description(body) != new_description:
        raise UnsupportedOperation(
            "WordPress accepted the request but did not persist the meta description; "
            "this site likely doesn't support this field."
        )
    return body
