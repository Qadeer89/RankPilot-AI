from datetime import datetime

from pydantic import BaseModel


class OnboardingStepResponse(BaseModel):
    key: str
    title: str
    mandatory: bool
    completed: bool
    skipped: bool
    detail: str


class OnboardingStatusResponse(BaseModel):
    steps: list[OnboardingStepResponse]
    welcomed_at: datetime | None
    completed_at: datetime | None
    all_mandatory_complete: bool


class SkipStepRequest(BaseModel):
    step_key: str
