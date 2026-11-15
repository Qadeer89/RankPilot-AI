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
    automation_policy: dict
    automation_mode: str
    crawl_frequency_hours: int
    ai_daily_budget_usd_override: float | None
    search_console_site_url: str | None
    ga4_property_id: str | None
    target_country: str | None
    additional_target_countries: list[str]
    target_language: str | None
    target_city: str | None

    model_config = {"from_attributes": True}


class WebsiteSettingsUpdateRequest(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    crawl_budget: int | None = Field(default=None, ge=1, le=10000)
    auto_execute_risk_tier_1: bool | None = None
    # RankPilot AI Phase 8 "Automation Modes": "audit", "copilot" or
    # "autopilot" -- validated against the enum in the endpoint, not
    # here, so an invalid value gets a clear 400 rather than a silent
    # pydantic coercion failure.
    automation_mode: str | None = None
    auto_execute_categories: dict[str, bool] | None = None
    crawl_frequency_hours: int | None = Field(default=None, ge=1, le=168)
    ai_daily_budget_usd_override: float | None = Field(default=None, ge=0)
    notify_on_regression: bool | None = None
    notify_on_auto_pipeline_summary: bool | None = None
    # Country-based SEO intelligence (SEO Growth Engine spec section 5).
    # ISO 3166-1 alpha-2; validated against that in the endpoint so an
    # invalid code gets a clear 400.
    target_country: str | None = Field(default=None, min_length=2, max_length=2)
    additional_target_countries: list[str] | None = None
    target_language: str | None = Field(default=None, min_length=2, max_length=8)
    target_city: str | None = Field(default=None, max_length=128)


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
