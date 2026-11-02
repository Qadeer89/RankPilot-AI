import socket

import pytest

from app.core import url_safety
from app.core.url_safety import UnsafeUrlError, normalize_url, validate_public_url


def test_normalize_url_lowercases_host_and_scheme():
    assert normalize_url("HTTPS://Example.COM/Path") == "https://example.com/Path"


def test_normalize_url_defaults_empty_path_to_slash():
    assert normalize_url("https://example.com") == "https://example.com/"


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com",
        "file:///etc/passwd",
        "javascript:alert(1)",
    ],
)
def test_rejects_disallowed_schemes(url):
    with pytest.raises(UnsafeUrlError):
        validate_public_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://localhost/",
        "http://169.254.169.254/latest/meta-data/",
        "http://10.0.0.5/",
        "http://192.168.1.1/",
        "http://[::1]/",
        "http://0.0.0.0/",
    ],
)
def test_rejects_private_and_loopback_and_metadata_hosts(url):
    with pytest.raises(UnsafeUrlError):
        validate_public_url(url)


def test_accepts_a_public_hostname(monkeypatch):
    # Stub DNS resolution so this test is deterministic and doesn't depend on
    # real network access: "example.com" resolves to a public IP.
    def fake_getaddrinfo(host, port):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]

    monkeypatch.setattr(url_safety.socket, "getaddrinfo", fake_getaddrinfo)

    safe_url = validate_public_url("https://example.com/some/page")
    assert safe_url.hostname == "example.com"
    assert safe_url.normalized_url == "https://example.com/some/page"
