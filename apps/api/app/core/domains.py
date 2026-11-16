"""One stable key per site, so "www.example.com", "Example.com." and a re-added copy are the same project."""

from __future__ import annotations


def domain_key(hostname: str | None) -> str:
    host = (hostname or "").strip().lower().rstrip(".")
    return host[4:] if host.startswith("www.") else host
