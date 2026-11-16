from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models.growth_recommendation import RecommendationLevel, RecommendationStatus


class GrowthRecommendationResponse(BaseModel):
    id: uuid.UUID
    recommendation_type: str
    title: str
    page_id: uuid.UUID | None
    proposed_url: str | None
    opportunity_id: uuid.UUID | None
    target_country: str | None
    keyword: str | None
    data_source: str
    problem: str
    recommended_action: str
    expected_benefit: str
    priority: RecommendationLevel
    difficulty: RecommendationLevel
    automation_available: bool
    requires_approval: bool
    validation_method: str
    evidence_json: dict
    status: RecommendationStatus
    updated_at: datetime
    # Derived from the execution pipeline's own records (app/growth/lifecycle.py).
    lifecycle: dict = {}

    model_config = {"from_attributes": True}


class UpdateGrowthRecommendationRequest(BaseModel):
    status: RecommendationStatus
