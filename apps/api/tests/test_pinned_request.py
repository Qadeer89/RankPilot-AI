"""app.core.url_safety.pinned_request -- the SSRF-safe replacement for
bare httpx.get/post/put calls, used by connector modules (Shopify,
WordPress) whose target host comes from user-supplied input evaluated
on every task execution, not just once at connect time (RP13-followup
security review)."""

import socket

import pytest

from app.core.url_safety import UnsafeUrlError, pinned_request


def _stub_dns(monkeypatch, ip="93.184.216.34"):
    def fake_getaddrinfo(host, port):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)


def test_rejects_private_host(monkeypatch):
    with pytest.raises(UnsafeUrlError):
        pinned_request("GET", "http://127.0.0.1/admin")


def test_rejects_disallowed_scheme(monkeypatch):
    with pytest.raises(UnsafeUrlError):
        pinned_request("GET", "ftp://example.com/")


def test_connects_to_pinned_ip_not_hostname(monkeypatch):
    _stub_dns(monkeypatch, ip="93.184.216.34")
    captured = {}

    class _FakeResponse:
        status_code = 200

    class _FakeClient:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def build_request(self, method, url, headers=None, **kwargs):
            captured["method"] = method
            captured["url"] = url
            captured["headers"] = headers
            request = type("Req", (), {"extensions": {}})()
            return request

        def send(self, request, auth=None):
            captured["sni_hostname"] = request.extensions.get("sni_hostname")
            captured["auth"] = auth
            return _FakeResponse()

    import httpx

    monkeypatch.setattr(httpx, "Client", _FakeClient)

    response = pinned_request("GET", "https://example.com/path", headers={"X-Test": "1"})

    assert response.status_code == 200
    assert captured["url"] == "https://93.184.216.34/path"
    assert captured["headers"]["Host"] == "example.com"
    assert captured["headers"]["X-Test"] == "1"
    assert captured["sni_hostname"] == "example.com"


def test_passes_auth_through_to_send(monkeypatch):
    _stub_dns(monkeypatch)
    captured = {}

    class _FakeResponse:
        status_code = 200

    class _FakeClient:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def build_request(self, method, url, headers=None, **kwargs):
            return type("Req", (), {"extensions": {}})()

        def send(self, request, auth=None):
            captured["auth"] = auth
            return _FakeResponse()

    import httpx

    monkeypatch.setattr(httpx, "Client", _FakeClient)

    pinned_request("GET", "https://example.com/", auth=("user", "pass"))
    assert captured["auth"] == ("user", "pass")
