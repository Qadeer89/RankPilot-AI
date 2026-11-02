import uuid
from datetime import date, datetime

from pydantic import BaseModel


class ReportResponse(BaseModel):
    id: uuid.UUID
    website_id: uuid.UUID
    period_start: date
    period_end: date
    report_type: str
    content_json: dict

    model_config = {"from_attributes": True}


class UsageMetricTotal(BaseModel):
    metric: str
    quantity: float
    unit: str
    estimated_cost: float


class UsageResponse(BaseModel):
    organization_id: uuid.UUID
    period_start: date
    period_end: date
    totals: list[UsageMetricTotal]


class AuditEventResponse(BaseModel):
    id: uuid.UUID
    actor_user_id: uuid.UUID | None
    action: str
    resource_type: str
    resource_id: str
    metadata_json: dict
    created_at: datetime

    model_config = {"from_attributes": True}
