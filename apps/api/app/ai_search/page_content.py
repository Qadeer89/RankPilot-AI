"""Reads what a landing page actually says, from the public page (the crawler stores structure, not body text).

The text is untrusted: it comes from a website and may contain instructions aimed at an AI. It is only ever
passed onward inside clearly delimited evidence blocks (see agent.py) and is never obeyed."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup

from app.crawler.extract import extract_page
from app.crawler.fetch import FetchError, safe_fetch
from app.models.website import Website

MAX_TEXT_CHARS = 12000
_STRIP = ("script", "style", "noscript", "nav", "footer", "header", "aside", "form", "svg", "iframe", "template")


@dataclass
class Block:
    heading: str | None
    level: int
    paragraphs: list[str] = field(default_factory=list)
    list_items: int = 0

    @property
    def text(self) -> str:
        return " ".join(self.paragraphs)


@dataclass
class PageContent:
    url: str
    available: bool
    error: str | None = None
    title: str | None = None
    meta_description: str | None = None
    headings: list[tuple[int, str]] = field(default_factory=list)
    blocks: list[Block] = field(default_factory=list)
    text: str = ""
    word_count: int = 0
    list_count: int = 0
    table_count: int = 0
    internal_link_count: int = 0
    external_link_count: int = 0
    schema_types: list[str] = field(default_factory=list)
    internal_links: list[str] = field(default_factory=list)


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def parse_content(html: str, *, url: str, hostname: str) -> PageContent:
    ext = extract_page(html, base_url=url, site_hostname=hostname)
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(list(_STRIP)):
        tag.decompose()
    root = soup.find("main") or soup.find("article") or soup.body or soup
    blocks: list[Block] = [Block(heading=None, level=0)]
    headings: list[tuple[int, str]] = []
    lists = tables = 0
    for el in root.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "table"]):
        name = el.name
        if name.startswith("h") and len(name) == 2:
            text = _clean(el.get_text(" "))
            if text:
                headings.append((int(name[1]), text))
                blocks.append(Block(heading=text, level=int(name[1])))
        elif name == "p":
            text = _clean(el.get_text(" "))
            if text:
                blocks[-1].paragraphs.append(text)
        elif name == "li":
            blocks[-1].list_items += 1
            text = _clean(el.get_text(" "))
            if text and el.find_parent("p") is None:
                blocks[-1].paragraphs.append(text)
        elif name == "table":
            tables += 1
    lists = len(root.find_all(["ul", "ol"]))
    body_text = _clean(" ".join(f"{b.heading or ''} {b.text}" for b in blocks))
    types: list[str] = []
    for block in ext.structured_data:
        parsed = block.parsed
        for node in (parsed if isinstance(parsed, list) else [parsed] if isinstance(parsed, dict) else []):
            if isinstance(node, dict) and node.get("@type"):
                t = node["@type"]
                types.extend(t if isinstance(t, list) else [str(t)])
    return PageContent(
        url=url, available=True, title=ext.title, meta_description=ext.meta_description, headings=headings,
        blocks=[b for b in blocks if b.heading or b.paragraphs], text=body_text[:MAX_TEXT_CHARS], word_count=len(body_text.split()),
        list_count=lists, table_count=tables, internal_link_count=len(ext.internal_links), external_link_count=len(ext.external_links),
        schema_types=sorted(set(types)), internal_links=list(ext.internal_links),
    )


def fetch_content(website: Website, url: str) -> PageContent:
    try:
        fetched = safe_fetch(url)
    except FetchError as exc:
        return PageContent(url=url, available=False, error=str(exc))
    if fetched.status_code != 200:
        return PageContent(url=url, available=False, error=f"The page answered HTTP {fetched.status_code}.")
    return parse_content(fetched.body, url=fetched.final_url, hostname=website.hostname)
