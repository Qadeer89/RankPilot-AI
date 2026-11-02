"""Domain ownership verification (RP-0203, WEBSITE_CONNECTORS.md #1, #4).

MVP supports the `html_file` method only: the owner uploads a file containing
a one-time token at a well-known path, and we fetch it back through the same
SSRF-safe path used for onboarding. DNS TXT and meta-tag methods are declared
in the schema for forward compatibility but are not yet implemented.
"""

from __future__ import annotations

import hashlib
import secrets
from urllib.parse import urlsplit, urlunsplit

import httpx

from app.core.url_safety import UnsafeUrlError, build_pinned_url, validate_public_url
from app.models.website_verification import VerificationMethod

VERIFICATION_FILENAME = "rankpilot-verify.txt"


def generate_token() -> str:
    return secrets.token_urlsafe(24)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def build_instructions(hostname: str, method: VerificationMethod, token: str) -> str:
    if method == VerificationMethod.html_file:
        return (
            f"Create a file at https://{hostname}/{VERIFICATION_FILENAME} "
            f"containing exactly this token: {token}"
        )
    raise NotImplementedError(f"Verification method '{method}' is not yet implemented.")


def check_html_file_verification(canonical_url: str, expected_token: str) -> tuple[bool, str]:
    """Fetch the verification file and compare its contents to the expected
    token. Returns (verified, detail_message).
    """
    parts = urlsplit(canonical_url)
    base = urlunsplit((parts.scheme, parts.netloc, "", "", ""))
    verify_url = f"{base}/{VERIFICATION_FILENAME}"

    try:
        safe_url = validate_public_url(verify_url)
    except UnsafeUrlError as exc:
        return False, f"Verification URL failed safety checks: {exc}"

    # Pin the connection to the validated IP (RP13-007): otherwise httpx
    # would re-resolve DNS at connect time, reopening the DNS-rebinding
    # window the check above just closed.
    pinned_url = build_pinned_url(safe_url)
    try:
        with httpx.Client(timeout=10.0, follow_redirects=False) as client:
            request = client.build_request("GET", pinned_url, headers={"Host": safe_url.hostname})
            request.extensions["sni_hostname"] = safe_url.hostname
            response = client.send(request)
    except httpx.HTTPError as exc:
        return False, f"Could not fetch verification file: {exc}"

    if response.status_code != 200:
        return False, f"Verification file returned HTTP {response.status_code}."

    body = response.text.strip()
    if body != expected_token:
        return False, "Verification file content did not match the expected token."

    return True, "Verification file matched the expected token."
