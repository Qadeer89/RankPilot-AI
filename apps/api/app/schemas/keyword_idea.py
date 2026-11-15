from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.keyword_idea import KeywordDataClassification, KeywordIdeaSource, KeywordIdeaStatus, SearchIntent


class RunKeywordDiscoveryRequest(BaseModel):
    country: str | None = Field(default=None, min_length=2, max_length=2)
    max_ideas: int = Field(default=20, ge=1, le=50)


class KeywordIdeaResponse(BaseModel):
    id: uuid.UUID
    keyword: str
    search_intent: SearchIntent
    source: KeywordIdeaSource
    data_classification: KeywordDataClassification
    country: str | None
    language: str | None
    relevance: float
    confidence: float
    recommended_content_type: str | None
    target_page_id: uuid.UUID | None
    proposed_title: str | None
    rationale: str
    cluster_key: str | None
    status: KeywordIdeaStatus
    created_at: datetime

    model_config = {"from_attributes": True}


class KeywordDiscoveryRunResponse(BaseModel):
    ideas: list[KeywordIdeaResponse]
    freshness_note: str = (
        "AI-generated ideas are relevance estimates, not verified search demand. "
        "Seed keywords come directly from this site's own content and Search Console data."
    )


class UpdateKeywordIdeaRequest(BaseModel):
    status: KeywordIdeaStatus
