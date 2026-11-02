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
