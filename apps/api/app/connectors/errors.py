"""Shared connector exception hierarchy.

Each connector module (wordpress, shopify, webflow, github_pr) raises
one of these so `app/execution/service.py` can catch connector failures
generically without importing every connector's own exception classes.
"""

from __future__ import annotations

from typing import Callable, TypeVar

import httpx

T = TypeVar("T")


class ConnectorError(RuntimeError):
    pass


class UnsupportedOperation(ConnectorError):
    pass


def safe_request(fn: Callable[..., T], *args, error_cls: type[ConnectorError] = ConnectorError, **kwargs) -> T:
    """Call an httpx request function, converting any transport-level
    failure (DNS failure, connection refused/reset, timeout, proxy
    error, ...) into a ConnectorError instead of letting it propagate as
    an unhandled exception. A connector that doesn't wrap its httpx
    calls this way 500s on a mistyped domain or a flaky network instead
    of surfacing a clean, user-facing error.

    `error_cls` lets a connector raise its own historical exception type
    (e.g. WordPressConnectorError) so existing callers that catch that
    specific type keep working unchanged.
    """
    try:
        return fn(*args, **kwargs)
    except httpx.RequestError as exc:
        raise error_cls(f"Network error calling connector API: {exc}") from exc
