"""Fixed-window rate limiting backed by Redis, for unauthenticated
endpoints an attacker could otherwise hammer indefinitely (RP13-004
added this for verification-token attempts via a per-row counter;
login/register have no equivalent per-attempt row to attach a counter
to, so this uses a Redis key instead).
"""

from __future__ import annotations

import redis
from fastapi import HTTPException, Request, status

from app.config import get_settings

_redis_client: redis.Redis | None = None


def _get_redis() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.Redis.from_url(get_settings().redis_url)
    return _redis_client


def enforce_rate_limit(key: str, *, max_attempts: int, window_seconds: int) -> None:
    """Raises HTTPException(429) once `key` has been hit more than
    `max_attempts` times within `window_seconds`. Fails open (lets the
    request through) if Redis itself is unreachable -- a rate limiter
    outage must not take down login/register entirely.
    """
    try:
        client = _get_redis()
        redis_key = f"rate_limit:{key}"
        count = client.incr(redis_key)
        if count == 1:
            client.expire(redis_key, window_seconds)
    except redis.RedisError:
        return
    if count > max_attempts:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many attempts. Please try again later.",
        )


def rate_limit_by_ip(request: Request, *, scope: str, max_attempts: int, window_seconds: int) -> None:
    client_ip = request.client.host if request.client else "unknown"
    enforce_rate_limit(f"{scope}:{client_ip}", max_attempts=max_attempts, window_seconds=window_seconds)
