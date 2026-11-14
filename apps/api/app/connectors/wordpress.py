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

from app.connectors.errors import ConnectorError, safe_request

YOAST_META_DESCRIPTION_KEY = "_yoast_wpseo_metadesc"
YOAST_CANONICAL_KEY = "_yoast_wpseo_canonical"
POST_TYPES_TO_SEARCH = ("pages", "posts")
MEDIA_RESOURCE_TYPE = "media"
REQUEST_TIMEOUT_SECONDS = 15.0

# Declared capability set (CW-001, addendum §4.3): the operations this
# connector actually implements. execution/service.py rejects any other
# operation before attempting it, instead of failing deep inside a write
# call or a raw AttributeError. set_alt_text lands on WordPress first
# (core wp/v2/media supports it on every install, unlike meta description)
# -- other connectors get it only once their content model is checked to
# actually support per-image alt text (RankPilot AI Phase 2 "AI Alt Text
# Generation").
# set_canonical is best-effort via the same Yoast meta-key mechanism as
# set_meta_description -- WordPress core has no canonical-URL REST
# field of its own (RankPilot AI Phase 3 "Canonical Tag Automation").
SUPPORTED_OPERATIONS = frozenset({"set_title", "set_meta_description", "set_alt_text", "set_canonical"})


class WordPressConnectorError(ConnectorError):
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
    response = safe_request(
        httpx.get,
        f"{_api_base(credentials.site_url)}/users/me",
        auth=credentials.auth,
        timeout=REQUEST_TIMEOUT_SECONDS,
        error_cls=WordPressConnectorError,
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
        response = safe_request(
            httpx.get,
            f"{_api_base(credentials.site_url)}/{post_type}",
            params={"slug": slug},
            auth=credentials.auth,
            timeout=REQUEST_TIMEOUT_SECONDS,
            error_cls=WordPressConnectorError,
        )
        if response.status_code == 200:
            results = response.json()
            if results:
                return post_type, results[0]["id"]

    raise WordPressConnectorError(f"No WordPress page or post found matching URL: {target_url}")


def find_media_by_url(credentials: WordPressCredentials, image_url: str) -> int:
    """Resolve an <img src> URL to a WordPress media attachment ID by
    matching the filename against the Media Library's search index, then
    confirming the candidate's own source_url actually matches (a search
    match alone isn't proof -- two different images can share a filename
    stem, e.g. two unrelated "hero.jpg" uploads on a busy site).
    """
    filename = urlsplit(image_url).path.rsplit("/", 1)[-1]
    stem = filename.rsplit(".", 1)[0] if "." in filename else filename
    if not stem:
        raise WordPressConnectorError(f"Could not derive a filename from image URL: {image_url}")

    response = safe_request(
        httpx.get,
        f"{_api_base(credentials.site_url)}/{MEDIA_RESOURCE_TYPE}",
        params={"search": stem},
        auth=credentials.auth,
        timeout=REQUEST_TIMEOUT_SECONDS,
        error_cls=WordPressConnectorError,
    )
    if response.status_code != 200:
        raise WordPressConnectorError(
            f"Could not search WordPress media: HTTP {response.status_code} {response.text[:200]}"
        )

    for candidate in response.json():
        source_url = candidate.get("source_url", "")
        if source_url == image_url or source_url.rsplit("/", 1)[-1] == filename:
            return candidate["id"]

    raise WordPressConnectorError(f"No WordPress media attachment found matching image URL: {image_url}")


def get_resource(credentials: WordPressCredentials, post_type: str, post_id: int) -> dict:
    response = safe_request(
        httpx.get,
        f"{_api_base(credentials.site_url)}/{post_type}/{post_id}",
        auth=credentials.auth,
        timeout=REQUEST_TIMEOUT_SECONDS,
        error_cls=WordPressConnectorError,
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


def current_alt_text(resource: dict) -> str:
    return resource.get("alt_text", "")


def current_canonical(resource: dict) -> str:
    return resource.get("meta", {}).get(YOAST_CANONICAL_KEY, "")


def update_title(credentials: WordPressCredentials, post_type: str, post_id: int, new_title: str) -> dict:
    response = safe_request(
        httpx.post,
        f"{_api_base(credentials.site_url)}/{post_type}/{post_id}",
        auth=credentials.auth,
        json={"title": new_title},
        timeout=REQUEST_TIMEOUT_SECONDS,
        error_cls=WordPressConnectorError,
    )
    if response.status_code != 200:
        raise WordPressConnectorError(
            f"Failed to update title on {post_type}/{post_id}: HTTP {response.status_code} {response.text[:200]}"
        )
    return response.json()


def update_meta_description(
    credentials: WordPressCredentials, post_type: str, post_id: int, new_description: str
) -> dict:
    response = safe_request(
        httpx.post,
        f"{_api_base(credentials.site_url)}/{post_type}/{post_id}",
        auth=credentials.auth,
        json={"meta": {YOAST_META_DESCRIPTION_KEY: new_description}},
        timeout=REQUEST_TIMEOUT_SECONDS,
        error_cls=WordPressConnectorError,
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


def update_canonical(
    credentials: WordPressCredentials, post_type: str, post_id: int, new_canonical: str
) -> dict:
    response = safe_request(
        httpx.post,
        f"{_api_base(credentials.site_url)}/{post_type}/{post_id}",
        auth=credentials.auth,
        json={"meta": {YOAST_CANONICAL_KEY: new_canonical}},
        timeout=REQUEST_TIMEOUT_SECONDS,
        error_cls=WordPressConnectorError,
    )
    if response.status_code == 400:
        raise UnsupportedOperation(
            "This WordPress site does not expose a REST-writable canonical URL field "
            "(expected a Yoast SEO-compatible meta key)."
        )
    if response.status_code != 200:
        raise WordPressConnectorError(
            f"Failed to update canonical URL on {post_type}/{post_id}: "
            f"HTTP {response.status_code} {response.text[:200]}"
        )
    body = response.json()
    if current_canonical(body) != new_canonical:
        raise UnsupportedOperation(
            "WordPress accepted the request but did not persist the canonical URL; "
            "this site likely doesn't support this field."
        )
    return body


def update_alt_text(credentials: WordPressCredentials, media_id: int, new_alt_text: str) -> dict:
    response = safe_request(
        httpx.post,
        f"{_api_base(credentials.site_url)}/{MEDIA_RESOURCE_TYPE}/{media_id}",
        auth=credentials.auth,
        json={"alt_text": new_alt_text},
        timeout=REQUEST_TIMEOUT_SECONDS,
        error_cls=WordPressConnectorError,
    )
    if response.status_code != 200:
        raise WordPressConnectorError(
            f"Failed to update alt text on media/{media_id}: HTTP {response.status_code} {response.text[:200]}"
        )
    body = response.json()
    if current_alt_text(body) != new_alt_text:
        raise UnsupportedOperation(
            "WordPress accepted the request but did not persist the image alt text."
        )
    return body
