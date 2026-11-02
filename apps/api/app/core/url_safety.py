"""SSRF-safe URL validation and normalization (RP-0202, SECURITY_SPECIFICATION.md #4).

Used at website onboarding time, and intended for reuse by the crawler in
Phase 2. A URL is "safe" only if its scheme is allowed and every address its
hostname resolves to is a public, routable address — never loopback, private,
link-local, multicast, reserved, or a cloud metadata endpoint.
"""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

from app.config import get_settings

settings = get_settings()

# 169.254.169.254 (AWS/GCP/Azure/DO metadata) already falls under link-local,
# but we check it explicitly in case a future allow-list ever narrows ranges.
_CLOUD_METADATA_HOSTS = {"169.254.169.254", "metadata.google.internal"}


class UnsafeUrlError(ValueError):
    """Raised when a submitted URL fails SSRF/scheme/host safety checks."""


@dataclass(frozen=True)
class SafeUrl:
    normalized_url: str
    hostname: str


def _is_disallowed_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return (
        ip.is_loopback
        or ip.is_private
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def normalize_url(raw_url: str) -> str:
    raw_url = raw_url.strip()
    parts = urlsplit(raw_url)
    scheme = parts.scheme.lower()
    netloc = parts.netloc.lower()
    path = parts.path or "/"
    return urlunsplit((scheme, netloc, path, "", ""))


def validate_public_url(raw_url: str) -> SafeUrl:
    """Validate that `raw_url` is safe to fetch or register.

    Raises UnsafeUrlError with a human-readable reason if the URL must be
    rejected. Callers should surface this as the API's `unsafe_url` error
    code rather than a generic validation error.
    """
    normalized = normalize_url(raw_url)
    parts = urlsplit(normalized)

    if parts.scheme not in settings.allowed_url_schemes:
        raise UnsafeUrlError(f"Scheme '{parts.scheme}' is not allowed; use http or https.")

    hostname = parts.hostname
    if not hostname:
        raise UnsafeUrlError("URL is missing a hostname.")

    if hostname in _CLOUD_METADATA_HOSTS:
        raise UnsafeUrlError("URL resolves to a blocked cloud metadata endpoint.")

    try:
        literal_ip = ipaddress.ip_address(hostname)
    except ValueError:
        literal_ip = None

    if literal_ip is not None and _is_disallowed_ip(literal_ip):
        raise UnsafeUrlError("URL host is a private, loopback, or otherwise disallowed address.")

    try:
        resolved = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise UnsafeUrlError(f"Could not resolve host '{hostname}'.") from exc

    for family, *_rest, sockaddr in resolved:
        address = sockaddr[0]
        ip_obj = ipaddress.ip_address(address)
        if _is_disallowed_ip(ip_obj):
            raise UnsafeUrlError(
                f"Host '{hostname}' resolves to a disallowed address ({address})."
            )

    return SafeUrl(normalized_url=normalized, hostname=hostname)
