"""Sanity CMS connector (CW-006/007/008, custom-website-write addendum
§4.1). First built for the Gul'sRehab founder pilot
(docs/CUSTOM_WEBSITE_WRITE_GAP_ANALYSIS.md §3), whose Sanity dataset was
read directly (not guessed) to confirm the schema this connector targets.

Only touches "blog" documents' `seoTitle`/`seoDescription` fields — the
dedicated SEO-metadata fields the real schema already separates from the
document's own editorial `title` — never the post's actual title, slug,
or body content. The schema's `service` document type has no SEO (or any
content) fields in Sanity at all, so this connector cannot and does not
claim to support changes to service pages; those would need a different
connector (GitHub, or a future Postgres-backed one) once that content's
real storage is identified.

Revision safety (CW-008) is native, not the generic value-comparison
fallback `execution/service.py` uses for the other connectors: every
patch is submitted with `ifRevisionID` set to the document's `_rev` at
read time, so Sanity's own mutate API rejects the write outright (and
this connector surfaces that as `UnsupportedOperation`) if the document
changed since it was read — a real optimistic-concurrency check, not an
approximation of one.

Not yet exercised against a live Sanity project from this environment
(no credential available in this sandbox) — implemented and unit-tested
against the documented GROQ query / mutate API shape, same caveat as the
other connectors built without a live credential.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

from app.connectors.errors import ConnectorError, UnsupportedOperation, safe_request

API_VERSION = "v2021-10-21"
REQUEST_TIMEOUT_SECONDS = 15.0
DOCUMENT_TYPE = "blog"

# Declared capability set (CW-001) -- only the dedicated SEO-metadata
# fields confirmed to exist on "blog" documents. See this module's
# docstring for why "service" documents are deliberately not supported.
SUPPORTED_OPERATIONS = frozenset({"set_title", "set_meta_description"})

FIELD_BY_OPERATION = {"set_title": "seoTitle", "set_meta_description": "seoDescription"}


@dataclass(frozen=True)
class SanityCredentials:
    project_id: str
    dataset: str
    token: str

    @property
    def headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"}


def _query_url(credentials: SanityCredentials) -> str:
    return f"https://{credentials.project_id}.api.sanity.io/{API_VERSION}/data/query/{credentials.dataset}"


def _mutate_url(credentials: SanityCredentials) -> str:
    return f"https://{credentials.project_id}.api.sanity.io/{API_VERSION}/data/mutate/{credentials.dataset}"


def _run_query(credentials: SanityCredentials, query: str, params: dict | None = None) -> dict | list | None:
    query_params = {"query": query}
    for key, value in (params or {}).items():
        query_params[f"${key}"] = json.dumps(value)

    response = safe_request(
        httpx.get,
        _query_url(credentials),
        params=query_params,
        headers=credentials.headers,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    if response.status_code != 200:
        raise ConnectorError(f"Sanity query failed: HTTP {response.status_code} {response.text[:200]}")
    return response.json().get("result")


def verify_credentials(credentials: SanityCredentials) -> dict:
    result = _run_query(credentials, "*[0]{_id}")
    return {"ok": True, "sample": result}


def _slug_from_url(target_url: str) -> str:
    path = urlsplit(target_url).path.strip("/")
    return path.rsplit("/", 1)[-1] if path else ""


def find_target(credentials: SanityCredentials, target_url: str) -> dict:
    """Resolve `target_url` to the "blog" document whose slug matches,
    returning its id, current revision, and the two SEO fields this
    connector can read/patch."""
    slug = _slug_from_url(target_url)
    query = f'*[_type == "{DOCUMENT_TYPE}" && slug.current == $slug][0]{{_id, _rev, seoTitle, seoDescription}}'
    result = _run_query(credentials, query, {"slug": slug})
    if not result:
        raise ConnectorError(f"No Sanity '{DOCUMENT_TYPE}' document found matching URL: {target_url}")
    return result


def get_current_value(credentials: SanityCredentials, target_ref: dict, operation: str) -> str:
    field = FIELD_BY_OPERATION.get(operation)
    if field is None:
        raise ValueError(f"Unsupported operation: {operation}")
    return target_ref.get(field) or ""


def apply_change(credentials: SanityCredentials, target_ref: dict, operation: str, new_value: str) -> dict:
    field = FIELD_BY_OPERATION.get(operation)
    if field is None:
        raise ValueError(f"Unsupported operation: {operation}")

    mutation = {
        "patch": {
            "id": target_ref["_id"],
            "ifRevisionID": target_ref["_rev"],
            "set": {field: new_value},
        }
    }
    response = safe_request(
        httpx.post,
        _mutate_url(credentials),
        json={"mutations": [mutation]},
        headers=credentials.headers,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    if response.status_code == 409:
        raise UnsupportedOperation(
            "Sanity rejected this write: the document changed since it was read "
            "(revision mismatch). Re-plan before retrying rather than overwriting it."
        )
    if response.status_code != 200:
        raise ConnectorError(
            f"Failed to patch Sanity document {target_ref['_id']}: HTTP {response.status_code} {response.text[:200]}"
        )
    return response.json()


def validate_change(
    credentials: SanityCredentials, target_ref: dict, operation: str, expected_value: str, apply_result: dict
) -> tuple[bool, dict]:
    field = FIELD_BY_OPERATION.get(operation)
    result = _run_query(credentials, f"*[_id == $id][0].{field}", {"id": target_ref["_id"]})
    actual = result or ""
    return actual == expected_value, {"expected": expected_value, "actual": actual}


def rollback(
    credentials: SanityCredentials, target_ref: dict, operation: str, before_value: str, after_state: dict
) -> dict:
    """Compensating patch (addendum §8: "use revision history or a
    compensating patch after checking the current revision"). The
    forward `apply_change` already advanced the document's revision, so
    this re-reads the current one rather than reusing the stale
    `target_ref["_rev"]`, which would always 409.
    """
    field = FIELD_BY_OPERATION.get(operation)
    if field is None:
        raise ValueError(f"Unsupported operation: {operation}")

    current = _run_query(credentials, "*[_id == $id][0]{_rev}", {"id": target_ref["_id"]})
    mutation: dict = {"patch": {"id": target_ref["_id"], "set": {field: before_value}}}
    if current and current.get("_rev"):
        mutation["patch"]["ifRevisionID"] = current["_rev"]

    response = safe_request(
        httpx.post,
        _mutate_url(credentials),
        json={"mutations": [mutation]},
        headers=credentials.headers,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    if response.status_code != 200:
        raise ConnectorError(
            f"Failed to roll back Sanity document {target_ref['_id']}: HTTP {response.status_code} {response.text[:200]}"
        )
    return response.json()
