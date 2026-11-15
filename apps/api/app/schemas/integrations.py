import uuid
from datetime import date

from pydantic import BaseModel


class ConnectUrlResponse(BaseModel):
    authorization_url: str


class SearchPropertiesResponse(BaseModel):
    site_urls: list[str]


class SelectPropertyRequest(BaseModel):
    site_url: str


class SyncResultResponse(BaseModel):
    rows_synced: int


class SearchPerformanceRow(BaseModel):
    query: str
    date: date
    clicks: int
    impressions: int
    ctr: float
    average_position: float
    country: str | None = None
    device: str | None = None


class SearchPerformanceResponse(BaseModel):
    source: str = "google_search_console"
    freshness_note: str = (
        "Search Console data is delayed and aggregated; it is not real-time ranking telemetry."
    )
    rows: list[SearchPerformanceRow]


class WindowStatsResponse(BaseModel):
    clicks: int
    impressions: int
    average_position: float


class PageTrendSignalResponse(BaseModel):
    page_id: uuid.UUID
    signals: list[str]
    prior: WindowStatsResponse
    recent: WindowStatsResponse


class RankingOpportunityResponse(BaseModel):
    query: str
    page_id: uuid.UUID | None
    average_position: float
    impressions: int


class CannibalizationCandidateResponse(BaseModel):
    query: str
    pages: list[dict]


class NewQueryResponse(BaseModel):
    query: str
    page_id: uuid.UUID | None
    impressions: int
    clicks: int
    average_position: float
    country: str | None


class SearchPerformanceIntelligenceResponse(BaseModel):
    freshness_note: str = (
        "Search Console data is delayed and aggregated; it is not real-time ranking telemetry."
    )
    country: str | None = None
    declining_pages: list[PageTrendSignalResponse]
    ranking_improvement_opportunities: list[RankingOpportunityResponse]
    keyword_cannibalization: list[CannibalizationCandidateResponse]
    new_queries: list[NewQueryResponse] = []


class Ga4PropertiesResponse(BaseModel):
    properties: list[dict]


class SelectGa4PropertyRequest(BaseModel):
    property_id: str


class Ga4MetricsRow(BaseModel):
    date: date
    sessions: int
    total_users: int
    conversions: int


class Ga4MetricsResponse(BaseModel):
    source: str = "ga4"
    freshness_note: str = "GA4 data is delayed and aggregated, not real-time."
    rows: list[Ga4MetricsRow]
