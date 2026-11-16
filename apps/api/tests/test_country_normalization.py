import socket

import pytest

from app.core import url_safety
from app.core.countries import (
    UNKNOWN_COUNTRY,
    country_name,
    list_countries,
    normalize_country,
    normalize_language,
    require_country,
    to_search_console_code,
)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("US", "US"), ("us", "US"), ("usa", "US"), (" USA ", "US"),
        ("UK", "GB"), ("gbr", "GB"),
        ("PK", "PK"), ("pak", "PK"),
        ("CA", "CA"), ("can", "CA"),
        ("AU", "AU"), ("aus", "AU"),
        ("zzz", "ZZ"), ("ZZ", "ZZ"),
    ],
)
def test_normalize_known_countries(raw, expected):
    assert normalize_country(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "  ", "qqq", "Atlantis", "United States", "U", "12"])
def test_normalize_unknown_returns_none(raw):
    assert normalize_country(raw) is None


def test_no_substring_matching():
    # "United" must not resolve to a country by substring.
    assert normalize_country("United") is None


def test_round_trip_to_search_console_code():
    assert to_search_console_code("US") == "usa"
    assert to_search_console_code("GB") == "gbr"
    assert normalize_country(to_search_console_code("PK")) == "PK"


def test_require_country_raises_on_invalid():
    with pytest.raises(ValueError):
        require_country("qqq")


def test_country_name_and_list():
    assert country_name("PK") == "Pakistan"
    codes = {c["code"] for c in list_countries()}
    assert {"US", "GB", "PK", "CA", "AU"} <= codes


def test_language_normalization():
    assert normalize_language("EN") == "en"
    assert normalize_language("english") in ("en", None)


def _reg(client, email):
    r = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "correct-horse-battery", "organization_name": f"Org {email}"},
    )
    token = r.json()["access_token"]
    me = client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    return token, me.json()["organizations"][0]["id"]


def _site(client, monkeypatch, token, org):
    monkeypatch.setattr(
        url_safety.socket, "getaddrinfo",
        lambda host, port: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))],
    )
    r = client.post(
        f"/api/v1/organizations/{org}/websites",
        json={"url": "https://example.com/", "display_name": "Ex"},
        headers={"Authorization": f"Bearer {token}"},
    )
    return r.json()["id"]


def test_reference_countries_requires_auth_and_lists(client):
    assert client.get("/api/v1/reference/countries").status_code in (401, 403)
    token, _ = _reg(client, "ref@example.com")
    r = client.get("/api/v1/reference/countries", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert any(c["code"] == "PK" for c in r.json())


def test_settings_normalize_dedupe_and_prune_languages(client, monkeypatch):
    token, org = _reg(client, "tm@example.com")
    site = _site(client, monkeypatch, token, org)
    h = {"Authorization": f"Bearer {token}"}
    url = f"/api/v1/organizations/{org}/websites/{site}/settings"
    r = client.patch(
        url,
        json={
            "target_country": "usa",
            "additional_target_countries": ["UK", "gbr", "US", "pak"],
            "target_languages_by_country": {"GB": "en", "PK": "ur", "CA": "fr"},
            "target_city": "Austin",
        },
        headers=h,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["target_country"] == "US"
    assert body["additional_target_countries"] == ["GB", "PK"]
    assert body["target_languages_by_country"] == {"GB": "en", "PK": "ur"}
    assert body["target_city"] == "Austin"

    # reopening shows saved values
    got = client.get(f"/api/v1/organizations/{org}/websites/{site}", headers=h).json()
    assert got["additional_target_countries"] == ["GB", "PK"]

    # clearing
    r = client.patch(url, json={"target_country": "", "additional_target_countries": []}, headers=h)
    assert r.json()["target_country"] is None


def test_settings_reject_invalid_country_and_language(client, monkeypatch):
    token, org = _reg(client, "bad@example.com")
    site = _site(client, monkeypatch, token, org)
    h = {"Authorization": f"Bearer {token}"}
    url = f"/api/v1/organizations/{org}/websites/{site}/settings"
    assert client.patch(url, json={"target_country": "qqq"}, headers=h).status_code == 400
    assert client.patch(url, json={"additional_target_countries": ["US", "qqq"]}, headers=h).status_code == 400
    assert client.patch(url, json={"target_language": "xx-not"}, headers=h).status_code in (400, 422)


def test_settings_tenant_isolation(client, monkeypatch):
    ta, oa = _reg(client, "iso-a@example.com")
    tb, ob = _reg(client, "iso-b@example.com")
    site = _site(client, monkeypatch, ta, oa)
    r = client.patch(
        f"/api/v1/organizations/{oa}/websites/{site}/settings",
        json={"target_country": "US"},
        headers={"Authorization": f"Bearer {tb}"},
    )
    assert r.status_code in (403, 404)
    r = client.patch(
        f"/api/v1/organizations/{ob}/websites/{site}/settings",
        json={"target_country": "US"},
        headers={"Authorization": f"Bearer {tb}"},
    )
    assert r.status_code == 404


def test_unknown_constant():
    assert UNKNOWN_COUNTRY == "ZZ"
    assert to_search_console_code("ZZ") == "zzz"
