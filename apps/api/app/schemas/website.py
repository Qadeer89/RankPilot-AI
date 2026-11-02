import uuid

from pydantic import BaseModel, Field


class WebsiteCreateRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2048)
    display_name: str = Field(min_length=1, max_length=255)
    purpose: str = Field(default="owned_pilot_site", max_length=64)


class WebsiteResponse(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    canonical_url: str
    hostname: str
    display_name: str
    verification_status: str
    platform: str
    crawl_budget: int
    status: str

    model_config = {"from_attributes": True}


class VerificationConfirmRequest(BaseModel):
    token: str = Field(min_length=1, max_length=255)


class VerificationInstructionsResponse(BaseModel):
    website_id: uuid.UUID
    method: str
    token: str
    instructions: str


class VerificationResultResponse(BaseModel):
    website_id: uuid.UUID
    verification_status: str
    verified: bool
    detail: str
