"""Rate limiting on /auth/login and /auth/register (RP13-followup: a
source-code security review found these had no throttling at all,
unlike verification-token attempts which RP13-004 already covers)."""

import pytest
import redis as redis_module
from fastapi import HTTPException

import app.api.v1.endpoints.auth as auth_module
from app.config import get_settings
from app.core.rate_limit import enforce_rate_limit, rate_limit_by_ip

settings = get_settings()


def _flush_rate_limit_keys():
    client = redis_module.Redis.from_url(settings.redis_url)
    for key in client.scan_iter("rate_limit:*"):
        client.delete(key)


def _reenable_real_rate_limiter(monkeypatch):
    # conftest's autouse fixture disables this for every other test;
    # these tests need the real thing.
    monkeypatch.setattr(auth_module, "rate_limit_by_ip", rate_limit_by_ip)
    _flush_rate_limit_keys()


def test_enforce_rate_limit_allows_up_to_max_attempts():
    _flush_rate_limit_keys()
    for _ in range(5):
        enforce_rate_limit("test_scope_a", max_attempts=5, window_seconds=600)
    # The 6th call exceeds max_attempts.
    with pytest.raises(HTTPException) as exc_info:
        enforce_rate_limit("test_scope_a", max_attempts=5, window_seconds=600)
    assert exc_info.value.status_code == 429


def test_enforce_rate_limit_keys_are_independent():
    _flush_rate_limit_keys()
    for _ in range(5):
        enforce_rate_limit("test_scope_b", max_attempts=5, window_seconds=600)
    # A different key has its own independent budget.
    enforce_rate_limit("test_scope_c", max_attempts=5, window_seconds=600)


def test_login_endpoint_429s_after_max_attempts(client, monkeypatch):
    _reenable_real_rate_limiter(monkeypatch)
    max_attempts = settings.auth_rate_limit_max_attempts

    for _ in range(max_attempts):
        response = client.post("/api/v1/auth/login", json={"email": "nobody@example.com", "password": "wrong"})
        assert response.status_code == 401

    response = client.post("/api/v1/auth/login", json={"email": "nobody@example.com", "password": "wrong"})
    assert response.status_code == 429


def test_register_endpoint_429s_after_max_attempts(client, monkeypatch):
    _reenable_real_rate_limiter(monkeypatch)
    max_attempts = settings.auth_rate_limit_max_attempts

    for i in range(max_attempts):
        response = client.post(
            "/api/v1/auth/register",
            json={
                "email": f"rate-limit-test-{i}@example.com",
                "password": "correct-horse-battery",
                "organization_name": f"Org {i}",
            },
        )
        assert response.status_code == 201

    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "rate-limit-test-overflow@example.com",
            "password": "correct-horse-battery",
            "organization_name": "Overflow Org",
        },
    )
    assert response.status_code == 429


def test_rate_limiter_fails_open_when_redis_unreachable(monkeypatch):
    # A rate limiter outage must not take down login/register entirely.
    import app.core.rate_limit as rate_limit_module

    class _BrokenRedis:
        def incr(self, *a, **k):
            raise redis_module.ConnectionError("redis is down")

    monkeypatch.setattr(rate_limit_module, "_get_redis", lambda: _BrokenRedis())
    enforce_rate_limit("test_scope_broken_redis", max_attempts=1, window_seconds=600)
