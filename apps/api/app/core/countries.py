"""One place for country and language codes.

Internal representation: ISO 3166-1 alpha-2, upper case ("US", "GB").
Google Search Console reports ISO alpha-3 in lower case ("usa", "gbr"),
plus "zzz" for an unknown region; website settings and keyword ideas use
alpha-2. Everything is normalized to the internal form at the boundary
(sync, API input) so stored values and filters always compare equal.
"""

from __future__ import annotations

import pycountry

# Search Console's "unknown region" bucket, kept as its own value rather
# than dropped so those clicks/impressions still count in totals.
UNKNOWN_COUNTRY = "ZZ"

_ALIASES = {"UK": "GB", "XKK": "XK", "ZZZ": UNKNOWN_COUNTRY}
# Codes in real use that ISO 3166-1 has not formally assigned.
_EXTRA = {"XK": ("Kosovo", "xkk"), UNKNOWN_COUNTRY: ("Unknown region", "zzz")}


def normalize_country(value: str | None) -> str | None:
    """Any supported spelling (alpha-2, alpha-3, any case, "UK") to the
    internal alpha-2 code. None for empty, unknown or unsupported input --
    never a guess.
    """
    if value is None:
        return None
    code = value.strip().upper()
    if not code:
        return None
    code = _ALIASES.get(code, code)
    if code in _EXTRA:
        return code
    if len(code) == 2:
        match = pycountry.countries.get(alpha_2=code)
    elif len(code) == 3:
        match = pycountry.countries.get(alpha_3=code)
    else:
        return None
    return match.alpha_2 if match else None


def require_country(value: str) -> str:
    code = normalize_country(value)
    if code is None:
        raise ValueError(f"'{value}' is not a recognized country code.")
    return code


def to_search_console_code(country: str | None) -> str | None:
    """Internal alpha-2 to Search Console's lower-case alpha-3."""
    code = normalize_country(country)
    if code is None:
        return None
    if code in _EXTRA:
        return _EXTRA[code][1]
    return pycountry.countries.get(alpha_2=code).alpha_3.lower()


def country_name(country: str | None) -> str | None:
    code = normalize_country(country)
    if code is None:
        return None
    if code in _EXTRA:
        return _EXTRA[code][0]
    match = pycountry.countries.get(alpha_2=code)
    return getattr(match, "common_name", None) or match.name


def list_countries() -> list[dict[str, str]]:
    countries = [{"code": c.alpha_2, "name": getattr(c, "common_name", None) or c.name} for c in pycountry.countries]
    countries.append({"code": "XK", "name": "Kosovo"})
    return sorted(countries, key=lambda c: c["name"])


def normalize_language(value: str | None) -> str | None:
    """ISO 639-1 two-letter language code, lower case, or None."""
    if value is None:
        return None
    code = value.strip().lower()
    if len(code) != 2:
        return None
    return code if pycountry.languages.get(alpha_2=code) else None


def require_language(value: str) -> str:
    code = normalize_language(value)
    if code is None:
        raise ValueError(f"'{value}' is not a recognized two-letter language code.")
    return code
