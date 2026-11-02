import uuid

from pydantic import BaseModel


class OpportunityResponse(BaseModel):
    id: uuid.UUID
    website_id: uuid.UUID
    page_id: uuid.UUID | None
    category: str
    title: str
    rationale: str
    impact_estimate: float
    confidence: float
    effort_estimate: float
    risk_tier: int
    score: float
    status: str

    model_config = {"from_attributes": True}
