from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class AddCompetitorDomainRequest(BaseModel):
    domain: str = Field(min_length=3, max_length=255)


class CompetitorDomainResponse(BaseModel):
    id: uuid.UUID
    domain: str
    last_analyzed_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class CompetitorPageSnapshotResponse(BaseModel):
    id: uuid.UUID
    url: str
    title: str | None
    meta_description: str | None
    word_count: int
    has_structured_data: bool
    fetch_error: str | None
    fetched_at: datetime

    model_config = {"from_attributes": True}
