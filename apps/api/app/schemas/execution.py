import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class WordPressConnectRequest(BaseModel):
    username: str = Field(min_length=1, max_length=255)
    application_password: str = Field(min_length=1, max_length=255)


class ShopifyConnectRequest(BaseModel):
    # Restricted to valid hostname characters (RP13-followup: an
    # unrestricted domain here is spliced straight into the connector's
    # outbound request URL -- see app.connectors.shopify -- so anything
    # beyond letters/digits/dot/hyphen is rejected before it ever gets
    # that far, in addition to the SSRF check the connector itself does
    # at request time via app.core.url_safety.pinned_request).
    shop_domain: str = Field(min_length=1, max_length=255, pattern=r"^[A-Za-z0-9.-]+$")
    access_token: str = Field(min_length=1, max_length=512)


class WebflowConnectRequest(BaseModel):
    site_id: str = Field(min_length=1, max_length=255)
    access_token: str = Field(min_length=1, max_length=512)


class SanityConnectRequest(BaseModel):
    # Sanity project IDs are lowercase alphanumeric + hyphen. Restricting
    # this prevents host injection: project_id is spliced directly into
    # a URL as a subdomain label (app.connectors.sanity), so an
    # unvalidated value containing e.g. ":" or "/" could redirect the
    # request to an entirely different host.
    project_id: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9-]+$")
    dataset: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    token: str = Field(min_length=1, max_length=512)


class GitHubConnectRequest(BaseModel):
    owner: str = Field(min_length=1, max_length=255)
    repo: str = Field(min_length=1, max_length=255)
    base_branch: str = Field(min_length=1, max_length=255, default="main")
    access_token: str = Field(min_length=1, max_length=512)


class GitHubAutoMergeRequest(BaseModel):
    auto_merge_on_ci_success: bool


class WebsiteConnectionResponse(BaseModel):
    id: uuid.UUID
    website_id: uuid.UUID
    connector_type: str
    status: str
    config_json: dict
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
    page_id: uuid.UUID | None
    seo_task_id: uuid.UUID
    connector_type: str
    before_state_json: dict
    after_state_json: dict
    actor_type: str
    executed_at: datetime
    validation_status: str

    model_config = {"from_attributes": True}


class DryRunResponse(BaseModel):
    operation: str
    target_url: str
    before_value: str
    proposed_value: str
    changed: bool


class WritesEnabledRequest(BaseModel):
    writes_enabled: bool


class DeploymentVerificationResponse(BaseModel):
    verified: bool
    checked_at: str
    expected: str | None = None
    actual: str | None = None
    fetched_url: str | None = None
    error: str | None = None


class RollbackRecordResponse(BaseModel):
    id: uuid.UUID
    change_record_id: uuid.UUID
    rollback_method: str
    status: str
    completed_at: datetime | None
    result_json: dict

    model_config = {"from_attributes": True}
