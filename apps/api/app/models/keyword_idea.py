"""AI-discovered keyword/topic ideas (SEO Growth Engine spec section 4
"AI Keyword and Topic Discovery") -- works without a paid Semrush/
Ahrefs/Moz account. Every row's `data_classification` says plainly
whether a number here is verified or an AI estimate; search volume,
keyword difficulty and CPC are never stored at all, since nothing in
this pipeline can verify them (spec section 5 "Country data rules":
never fabricate monthly search volume, keyword difficulty, competition
score, ranking position or CPC).
"""

from __future__ import annotations

import enum
import uuid

from sqlalchemy import JSON, Enum, Float, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class SearchIntent(str, enum.Enum):
    informational = "informational"
    commercial = "commercial"
    transactional = "transactional"
    navigational = "navigational"
    local = "local"


class KeywordIdeaSource(str, enum.Enum):
    # Derived deterministically from the site's own crawled pages, GSC
    # queries, or user-provided seed keywords -- not an AI guess.
    seed = "seed"
    ai_generated = "ai_generated"
    public_suggestion = "public_suggestion"
    # A content-gap idea produced by comparing this site's own topics
    # against a competitor's publicly crawled pages (spec section 4D).
    competitor_gap = "competitor_gap"


class KeywordDataClassification(str, enum.Enum):
    """What kind of claim this row actually is (spec section 5). The
    UI must label every keyword with this, never present an estimate
    as verified demand.
    """

    verified_first_party = "verified_first_party"
    verified_external_source = "verified_external_source"
    public_search_suggestion = "public_search_suggestion"
    ai_generated_idea = "ai_generated_idea"
    ai_estimated_relevance = "ai_estimated_relevance"
    unavailable = "unavailable"


class KeywordIdeaStatus(str, enum.Enum):
    new = "new"
    dismissed = "dismissed"
    actioned = "actioned"


class KeywordIdea(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "keyword_ideas"
    __table_args__ = (
        UniqueConstraint("website_id", "keyword", "country", name="uq_keyword_idea_identity"),
    )

    website_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("websites.id", ondelete="CASCADE"), nullable=False, index=True
    )
    keyword: Mapped[str] = mapped_column(String(512), nullable=False)
    search_intent: Mapped[SearchIntent] = mapped_column(Enum(SearchIntent, name="keyword_idea_search_intent"), nullable=False)
    source: Mapped[KeywordIdeaSource] = mapped_column(Enum(KeywordIdeaSource, name="keyword_idea_source"), nullable=False)
    data_classification: Mapped[KeywordDataClassification] = mapped_column(
        Enum(KeywordDataClassification, name="keyword_idea_data_classification"), nullable=False
    )
    # ISO 3166-1 alpha-2, matching Website.target_country's format
    # (distinct from KeywordObservation.country, which keeps GSC's own
    # alpha-3 codes as-returned) -- None means not country-specific.
    country: Mapped[str | None] = mapped_column(String(2), nullable=True, index=True)
    language: Mapped[str | None] = mapped_column(String(8), nullable=True)
    relevance: Mapped[float] = mapped_column(Float, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    recommended_content_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    target_page_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pages.id", ondelete="SET NULL"), nullable=True
    )
    proposed_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    cluster_key: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    status: Mapped[KeywordIdeaStatus] = mapped_column(
        Enum(KeywordIdeaStatus, name="keyword_idea_status"), default=KeywordIdeaStatus.new, nullable=False
    )
    evidence_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    website: Mapped["Website"] = relationship()
    target_page: Mapped["Page | None"] = relationship()
