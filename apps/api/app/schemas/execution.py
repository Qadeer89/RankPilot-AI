import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class WordPressConnectRequest(BaseModel):
    username: str = Field(min_length=1, max_length=255)
    application_password: str = Field(min_length=1, max_length=255)


class WebsiteConnectionResponse(BaseModel):
    id: uuid.UUID
    website_id: uuid.UUID
    connector_type: str
    status: str
    last_verified_at: datetime | None

    model_config = {"from_attributes": True}


class SEOTaskResponse(BaseModel):
    id: uuid.UUID
    website_id: uuid.UUID
    opportunity_id: uuid.UUID | None
    task_type: str
    status: str
    risk_tier: int
    proposed_change_json: dict
    approval_status: str

    model_config = {"from_attributes": True}


class ApprovalDecisionRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=2048)


class ChangeRecordResponse(BaseModel):
    id: uuid.UUID
    website_id: uuid.UUID
    seo_task_id: uuid.UUID
    connector_type: str
    before_state_json: dict
    after_state_json: dict
    actor_type: str
    executed_at: datetime
    validation_status: str

    model_config = {"from_attributes": True}


class RollbackRecordResponse(BaseModel):
    id: uuid.UUID
    change_record_id: uuid.UUID
    rollback_method: str
    status: str
    completed_at: datetime | None
    result_json: dict

    model_config = {"from_attributes": True}
