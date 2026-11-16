"""The site's title template, learned from its own crawled page titles."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.keywords.seed_generation import _latest_snapshots
from app.models.website import Website
from app.seo_rules.title_template import TitleSuffix, detect_title_suffix


def site_title_suffix(db: Session, website: Website) -> TitleSuffix | None:
    titles = [s.title for s in _latest_snapshots(db, website.id) if s.title and (s.status_code or 200) < 400]
    return detect_title_suffix(titles)
