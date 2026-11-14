"""Google PageSpeed Insights API integration (RankPilot AI Phase 4
"Core Web Vitals").

PageSpeed Insights returns two genuinely different kinds of data in
one response, and this module keeps them separate rather than
blending them into one number:

- Lab data (`lighthouseResult`): a single simulated run, always
  present, used for the deterministic performance_score.
- Field data (`loadingExperience`): real Chrome User Experience
  Report (CrUX) data from actual visitors over the last 28 days --
  absent entirely for low-traffic pages, in which case this module
  reports it as None rather than a fabricated 0.

No OAuth: a single API key, same "optional, unset means simply not
measured" pattern as every other external integration in this codebase
(app/config.py).
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

PAGESPEED_API_BASE = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"

# Lighthouse audit IDs for the metrics this module reports as lab data.
# total-blocking-time is lab's own proxy for responsiveness: Lighthouse
# cannot measure real Interaction to Next Paint in a scripted run with
# no real user input, so this is deliberately not called "INP" --
# INP itself only ever comes from field data below.
_LCP_AUDIT = "largest-contentful-paint"
_CLS_AUDIT = "cumulative-layout-shift"
_TBT_AUDIT = "total-blocking-time"

# CrUX field-data metric keys, when Google has enough real-user traffic
# to report them.
_FIELD_LCP_KEY = "LARGEST_CONTENTFUL_PAINT_MS"
_FIELD_CLS_KEY = "CUMULATIVE_LAYOUT_SHIFT_SCORE"
_FIELD_INP_KEY = "INTERACTION_TO_NEXT_PAINT"


class PageSpeedApiError(RuntimeError):
    pass


@dataclass(frozen=True)
class CoreWebVitalsResult:
    strategy: str  # "mobile" or "desktop"
    lab_performance_score: float | None  # 0-100, from Lighthouse's own category score
    lab_lcp_ms: float | None
    lab_cls: float | None
    lab_tbt_ms: float | None
    field_lcp_ms: float | None  # None when Google has no real-user data for this page
    field_cls: float | None
    field_inp_ms: float | None


def _audit_numeric_value(lighthouse_result: dict, audit_id: str) -> float | None:
    audit = lighthouse_result.get("audits", {}).get(audit_id)
    if not audit:
        return None
    value = audit.get("numericValue")
    return float(value) if value is not None else None


def fetch_core_web_vitals(
    url: str, *, api_key: str, strategy: str = "mobile", timeout_seconds: float = 30.0
) -> CoreWebVitalsResult:
    """Run a live PageSpeed Insights audit for `url`. Raises
    PageSpeedApiError on any failure (bad key, quota exceeded, the
    target URL itself failing to load for Lighthouse, ...). Never
    retries internally -- a scheduled sync task decides whether/when
    to retry a failed page, not this function.
    """
    if strategy not in ("mobile", "desktop"):
        raise ValueError(f"strategy must be 'mobile' or 'desktop', got {strategy!r}")

    try:
        response = httpx.get(
            PAGESPEED_API_BASE,
            params={"url": url, "key": api_key, "strategy": strategy, "category": "performance"},
            timeout=timeout_seconds,
        )
    except httpx.RequestError as exc:
        raise PageSpeedApiError(f"Network error calling PageSpeed Insights: {exc}") from exc

    if response.status_code != 200:
        raise PageSpeedApiError(
            f"PageSpeed Insights returned HTTP {response.status_code} for {url}: {response.text[:300]}"
        )

    body = response.json()
    lighthouse_result = body.get("lighthouseResult", {})
    performance_category = lighthouse_result.get("categories", {}).get("performance", {})
    score_fraction = performance_category.get("score")
    lab_performance_score = round(score_fraction * 100, 1) if score_fraction is not None else None

    loading_experience = body.get("loadingExperience", {}).get("metrics", {})

    def _field_metric(key: str) -> float | None:
        metric = loading_experience.get(key)
        if not metric:
            return None
        percentile = metric.get("percentile")
        return float(percentile) if percentile is not None else None

    # CrUX reports CLS as an integer percentile in units of 0.01 (since
    # percentile values must be integers) -- divide back to the
    # standard CLS decimal scale (e.g. 5 -> 0.05).
    field_cls_percentile = _field_metric(_FIELD_CLS_KEY)
    field_cls = field_cls_percentile / 100.0 if field_cls_percentile is not None else None

    return CoreWebVitalsResult(
        strategy=strategy,
        lab_performance_score=lab_performance_score,
        lab_lcp_ms=_audit_numeric_value(lighthouse_result, _LCP_AUDIT),
        lab_cls=_audit_numeric_value(lighthouse_result, _CLS_AUDIT),
        lab_tbt_ms=_audit_numeric_value(lighthouse_result, _TBT_AUDIT),
        field_lcp_ms=_field_metric(_FIELD_LCP_KEY),
        field_cls=field_cls,
        field_inp_ms=_field_metric(_FIELD_INP_KEY),
    )
