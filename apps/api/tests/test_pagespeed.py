import pytest

from app.integrations import pagespeed


class _FakeResponse:
    def __init__(self, status_code: int, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = str(payload)

    def json(self):
        return self._payload


LIGHTHOUSE_BODY_WITH_FIELD_DATA = {
    "lighthouseResult": {
        "categories": {"performance": {"score": 0.87}},
        "audits": {
            "largest-contentful-paint": {"numericValue": 1800.0},
            "cumulative-layout-shift": {"numericValue": 0.05},
            "total-blocking-time": {"numericValue": 120.0},
        },
    },
    "loadingExperience": {
        "metrics": {
            "LARGEST_CONTENTFUL_PAINT_MS": {"percentile": 2100},
            "CUMULATIVE_LAYOUT_SHIFT_SCORE": {"percentile": 8},
            "INTERACTION_TO_NEXT_PAINT": {"percentile": 180},
        }
    },
}

LIGHTHOUSE_BODY_WITHOUT_FIELD_DATA = {
    "lighthouseResult": {
        "categories": {"performance": {"score": 0.5}},
        "audits": {
            "largest-contentful-paint": {"numericValue": 4000.0},
            "cumulative-layout-shift": {"numericValue": 0.3},
            "total-blocking-time": {"numericValue": 600.0},
        },
    },
    "loadingExperience": {},
}


def test_fetch_core_web_vitals_parses_lab_and_field_data(monkeypatch):
    monkeypatch.setattr(
        pagespeed.httpx, "get", lambda *a, **k: _FakeResponse(200, LIGHTHOUSE_BODY_WITH_FIELD_DATA)
    )
    result = pagespeed.fetch_core_web_vitals("https://example.com/", api_key="key123")

    assert result.lab_performance_score == 87.0
    assert result.lab_lcp_ms == 1800.0
    assert result.lab_cls == 0.05
    assert result.lab_tbt_ms == 120.0
    assert result.field_lcp_ms == 2100.0
    assert result.field_cls == 0.08
    assert result.field_inp_ms == 180.0


def test_fetch_core_web_vitals_leaves_field_data_as_none_when_crux_has_no_data(monkeypatch):
    """A low-traffic page genuinely has no CrUX field data -- this must
    be reported as None, never a fabricated 0 that would look like a
    perfect real-user score."""
    monkeypatch.setattr(
        pagespeed.httpx, "get", lambda *a, **k: _FakeResponse(200, LIGHTHOUSE_BODY_WITHOUT_FIELD_DATA)
    )
    result = pagespeed.fetch_core_web_vitals("https://example.com/", api_key="key123")

    assert result.lab_performance_score == 50.0
    assert result.field_lcp_ms is None
    assert result.field_cls is None
    assert result.field_inp_ms is None


def test_fetch_core_web_vitals_raises_on_http_error(monkeypatch):
    monkeypatch.setattr(pagespeed.httpx, "get", lambda *a, **k: _FakeResponse(403, {"error": "bad key"}))
    with pytest.raises(pagespeed.PageSpeedApiError, match="HTTP 403"):
        pagespeed.fetch_core_web_vitals("https://example.com/", api_key="bad-key")


def test_fetch_core_web_vitals_wraps_network_errors(monkeypatch):
    import httpx

    def fake_get(*a, **k):
        raise httpx.ConnectError("DNS resolution failed")

    monkeypatch.setattr(pagespeed.httpx, "get", fake_get)
    with pytest.raises(pagespeed.PageSpeedApiError, match="Network error"):
        pagespeed.fetch_core_web_vitals("https://example.com/", api_key="key123")


def test_fetch_core_web_vitals_rejects_an_invalid_strategy():
    with pytest.raises(ValueError, match="strategy must be"):
        pagespeed.fetch_core_web_vitals("https://example.com/", api_key="key123", strategy="tablet")


def test_fetch_core_web_vitals_passes_strategy_and_key_as_query_params(monkeypatch):
    captured = {}

    def fake_get(url, params=None, timeout=None):
        captured.update(params)
        return _FakeResponse(200, LIGHTHOUSE_BODY_WITH_FIELD_DATA)

    monkeypatch.setattr(pagespeed.httpx, "get", fake_get)
    pagespeed.fetch_core_web_vitals("https://example.com/about", api_key="key123", strategy="desktop")

    assert captured["url"] == "https://example.com/about"
    assert captured["key"] == "key123"
    assert captured["strategy"] == "desktop"


LIGHTHOUSE_RESULT_WITH_OPPORTUNITIES = {
    "categories": {"performance": {"score": 0.5}},
    "audits": {
        "render-blocking-resources": {
            "title": "Eliminate render-blocking resources",
            "details": {"overallSavingsMs": 300.0},
        },
        "unused-javascript": {
            "title": "Reduce unused JavaScript",
            "details": {"overallSavingsMs": 900.0},
        },
        "unminified-css": {
            "title": "Minify CSS",
            "details": {"overallSavingsMs": 0},
        },
        "modern-image-formats": {
            "title": "Serve images in next-gen formats",
        },
    },
}


def test_extract_opportunities_sorts_by_savings_descending():
    opportunities = pagespeed._extract_opportunities(LIGHTHOUSE_RESULT_WITH_OPPORTUNITIES)
    assert [o.audit_id for o in opportunities] == ["unused-javascript", "render-blocking-resources"]
    assert opportunities[0].savings_ms == 900.0
    assert opportunities[0].title == "Reduce unused JavaScript"


def test_extract_opportunities_excludes_zero_or_missing_savings():
    opportunities = pagespeed._extract_opportunities(LIGHTHOUSE_RESULT_WITH_OPPORTUNITIES)
    audit_ids = {o.audit_id for o in opportunities}
    assert "unminified-css" not in audit_ids
    assert "modern-image-formats" not in audit_ids


def test_extract_opportunities_caps_at_max_reported():
    audits = {
        audit_id: {"title": f"Audit {i}", "details": {"overallSavingsMs": float(100 + i)}}
        for i, audit_id in enumerate(pagespeed._OPPORTUNITY_AUDIT_IDS)
    }
    opportunities = pagespeed._extract_opportunities({"audits": audits})
    assert len(opportunities) == pagespeed.MAX_OPPORTUNITIES_REPORTED


def test_extract_opportunities_returns_empty_list_when_no_audits_present():
    assert pagespeed._extract_opportunities({"audits": {}}) == []


def test_fetch_core_web_vitals_includes_opportunities(monkeypatch):
    body = {
        "lighthouseResult": LIGHTHOUSE_RESULT_WITH_OPPORTUNITIES,
        "loadingExperience": {},
    }
    monkeypatch.setattr(pagespeed.httpx, "get", lambda *a, **k: _FakeResponse(200, body))
    result = pagespeed.fetch_core_web_vitals("https://example.com/", api_key="key123")

    assert [o.audit_id for o in result.opportunities] == ["unused-javascript", "render-blocking-resources"]
