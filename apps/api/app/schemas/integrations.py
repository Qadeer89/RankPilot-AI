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


class SearchPerformanceResponse(BaseModel):
    source: str = "google_search_console"
    freshness_note: str = (
        "Search Console data is delayed and aggregated; it is not real-time ranking telemetry."
    )
    rows: list[SearchPerformanceRow]


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
