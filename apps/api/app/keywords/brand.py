"""Brand searches: queries people type to reach the business they already know ("contact Brand for inquiries", "Brand login").

They are not SEO opportunities: the person already knows the name, so there is no new audience to win. They are still shown in the
keyword list, but labelled, and they never become growth recommendations. Detected deterministically from the project's own name
and domain, no AI involved."""

from __future__ import annotations

import re

_NAVIGATIONAL_WORDS = frozenset(
    "contact contacts inquiry inquiries enquiry enquiries login log signin sign account address location locations directions map phone number "
    "email hours opening timings timing booking appointment website official".split()
)


def _norm(text: str) -> str:
    """Lower-case letters and digits only, apostrophes removed so "Gul's Rehab" and "Guls Rehab" compare equal."""
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", re.sub(r"['’]", "", (text or "").lower()))).strip()


def brand_names(display_name: str | None, hostname: str | None) -> list[str]:
    names = []
    if display_name:
        names.append(_norm(display_name))
    if hostname:
        host = hostname.lower().removeprefix("www.")
        label = host.split(".")[0]
        names.append(_norm(label.replace("-", " ")))
        names.append(_norm(label))
    return [n for n in dict.fromkeys(names) if len(n) >= 4]


def is_brand_navigational(keyword: str, search_intent: str | None, display_name: str | None, hostname: str | None) -> bool:
    """The keyword names the business itself AND is asking to reach it (contact, login, address, ...) or the AI marked it navigational."""
    text = _norm(keyword)
    squashed = text.replace(" ", "")
    mentions_brand = any(b in text or b.replace(" ", "") in squashed for b in brand_names(display_name, hostname))
    if not mentions_brand:
        return False
    return search_intent == "navigational" or bool(set(text.split()) & _NAVIGATIONAL_WORDS)
