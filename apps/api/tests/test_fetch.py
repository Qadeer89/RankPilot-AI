"""Direct tests of app.crawler.fetch.safe_fetch's real implementation
(RP13-005/006/007): response size limits, redirect-hop ceiling, and
pinning the actual connection to the IP validated by validate_public_url
so DNS cannot change between validation and connect time.
"""

import socket

import httpx
import pytest

from app.core import url_safety
from app.crawler.fetch import FetchError, safe_fetch


def _stub_dns(monkeypatch, host_to_ip: dict[str, str]):
    def fake_getaddrinfo(host, port):
        ip = host_to_ip[host]
        family = socket.AF_INET6 if ":" in ip else socket.AF_INET
        return [(family, socket.SOCK_STREAM, 6, "", (ip, 0))]

    monkeypatch.setattr(url_safety.socket, "getaddrinfo", fake_getaddrinfo)


class _FakeResponse:
    def __init__(self, status_code=200, headers=None, body=b"ok", is_redirect=False):
        self.status_code = status_code
        self.headers = headers or {}
        self._body = body
        self.is_redirect = is_redirect
        self.encoding = "utf-8"

    def iter_bytes(self):
        chunk_size = 4096
        for i in range(0, len(self._body), chunk_size):
            yield self._body[i : i + chunk_size]


def test_safe_fetch_connects_to_the_validated_ip_not_the_hostname(monkeypatch):
    """Even if DNS were to change right after validation, the actual
    connection must target the IP that was checked -- not re-resolve.
    """
    _stub_dns(monkeypatch, {"example.com": "93.184.216.34"})

    captured = {}

    def fake_send(self, request):
        captured["url"] = request.url
        captured["host_header"] = request.headers.get("host")
        captured["sni_hostname"] = request.extensions.get("sni_hostname")
        return _FakeResponse(status_code=200, body=b"hello")

    monkeypatch.setattr(httpx.Client, "send", fake_send)

    result = safe_fetch("https://example.com/page")

    assert captured["url"].host == "93.184.216.34"
    assert captured["host_header"] == "example.com"
    assert captured["sni_hostname"] == "example.com"
    assert result.status_code == 200
    assert result.body == "hello"
    assert result.final_url == "https://example.com/page"


def test_safe_fetch_pins_ipv6_literal_correctly(monkeypatch):
    # A real, public, globally-routable IPv6 address (Google public DNS) --
    # not one of the reserved documentation ranges like 2001:db8::/32.
    _stub_dns(monkeypatch, {"example.com": "2001:4860:4860::8888"})

    captured = {}

    def fake_send(self, request):
        captured["url"] = request.url
        return _FakeResponse(status_code=200, body=b"hello")

    monkeypatch.setattr(httpx.Client, "send", fake_send)

    safe_fetch("https://example.com/")
    assert captured["url"].host == "2001:4860:4860::8888"


def test_safe_fetch_rejects_oversized_response_via_content_length(monkeypatch):
    _stub_dns(monkeypatch, {"example.com": "93.184.216.34"})

    def fake_send(self, request):
        return _FakeResponse(status_code=200, headers={"content-length": str(50 * 1024 * 1024)})

    monkeypatch.setattr(httpx.Client, "send", fake_send)

    with pytest.raises(FetchError, match="too large"):
        safe_fetch("https://example.com/huge")


def test_safe_fetch_rejects_oversized_response_while_streaming(monkeypatch):
    _stub_dns(monkeypatch, {"example.com": "93.184.216.34"})

    oversized_body = b"x" * (6 * 1024 * 1024)  # over the 5 MB cap, no content-length header

    def fake_send(self, request):
        return _FakeResponse(status_code=200, body=oversized_body)

    monkeypatch.setattr(httpx.Client, "send", fake_send)

    with pytest.raises(FetchError, match="exceeded the maximum allowed size"):
        safe_fetch("https://example.com/huge-stream")


def test_safe_fetch_enforces_redirect_ceiling(monkeypatch):
    _stub_dns(monkeypatch, {"example.com": "93.184.216.34"})

    def fake_send(self, request):
        # Always redirect to itself -- an infinite redirect loop.
        return _FakeResponse(status_code=302, headers={"location": "/next"}, is_redirect=True)

    monkeypatch.setattr(httpx.Client, "send", fake_send)

    with pytest.raises(FetchError, match="Exceeded max redirects"):
        safe_fetch("https://example.com/loop", max_redirects=3)


def test_safe_fetch_revalidates_ssrf_on_every_redirect_hop(monkeypatch):
    """A redirect to a private IP must be rejected even if the first hop
    was a validated public host.
    """
    _stub_dns(monkeypatch, {"example.com": "93.184.216.34"})

    call_count = {"n": 0}

    def fake_send(self, request):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return _FakeResponse(
                status_code=302, headers={"location": "http://169.254.169.254/latest/meta-data/"}, is_redirect=True
            )
        raise AssertionError("should never reach the second hop: SSRF validation must reject it first")

    monkeypatch.setattr(httpx.Client, "send", fake_send)

    with pytest.raises(FetchError, match="unsafe_url"):
        safe_fetch("https://example.com/redirect-to-metadata")


def test_safe_fetch_follows_a_safe_redirect_to_completion(monkeypatch):
    _stub_dns(monkeypatch, {"example.com": "93.184.216.34"})

    call_count = {"n": 0}

    def fake_send(self, request):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return _FakeResponse(status_code=301, headers={"location": "/final"}, is_redirect=True)
        return _FakeResponse(status_code=200, body=b"final page")

    monkeypatch.setattr(httpx.Client, "send", fake_send)

    result = safe_fetch("https://example.com/start")
    assert result.status_code == 200
    assert result.body == "final page"
    assert result.redirect_chain == ["https://example.com/start"]
