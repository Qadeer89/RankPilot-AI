"""Nothing externally visible may be tied to one domain: change the settings and every address follows."""

import pytest

from app.config import Settings, get_settings
from app.core.deployment import crawler_user_agent, deployment_problems, is_indexable, webhook_url


def _s(**kw):
    base = dict(environment="production", frontend_base_url="https://app.alpha.test", api_public_url="https://api.alpha.test",
                cors_allowed_origins=("https://app.alpha.test",), lemonsqueezy_test_mode=False, lemonsqueezy_webhook_secret="x",
                jwt_secret="a-real-secret-value-for-tests-only-0123456789",
                google_oauth_redirect_uri="https://api.alpha.test/cb1", google_ga4_oauth_redirect_uri="https://api.alpha.test/cb2")
    base.update(kw)
    return Settings(**base)


@pytest.mark.parametrize("front,api", [("https://app.alpha.test", "https://api.alpha.test"), ("https://rank.other.example", "https://backend.other.example/")])
def test_addresses_follow_settings(front, api):
    s = _s(frontend_base_url=front, api_public_url=api)
    assert webhook_url(s) == f"{api.rstrip('/')}/api/v1/billing/webhooks/lemonsqueezy"
    assert crawler_user_agent(s) == f"RankPilotBot/0.1 (+{front}/bot)"
    assert crawler_user_agent(_s(crawler_info_url="https://x.test/about-bot")).endswith("(+https://x.test/about-bot)")


def test_consistent_production_has_no_problems():
    assert deployment_problems(_s()) == []


def test_each_misconfiguration_is_reported():
    codes = {p["code"] for p in deployment_problems(_s(frontend_base_url="http://localhost:3100", api_public_url="http://api.alpha.test",
                                                       lemonsqueezy_test_mode=True, lemonsqueezy_webhook_secret=None, cors_allowed_origins=("https://elsewhere.test",),
                                                       google_oauth_redirect_uri="https://old-domain.test/cb"))}
    assert {"local_url_in_production", "insecure_url_in_production", "test_payments_in_production", "no_webhook_secret",
            "cors_missing_frontend", "oauth_redirect_host_mismatch"} <= codes


def test_live_payments_outside_production_and_unknown_environment_are_flagged():
    codes = {p["code"] for p in deployment_problems(_s(environment="staging", lemonsqueezy_test_mode=False))}
    assert "live_payments_outside_production" in codes
    assert "unknown_environment" in {p["code"] for p in deployment_problems(_s(environment="prod2"))}


def test_only_production_is_indexable():
    assert is_indexable(_s()) and not is_indexable(_s(environment="staging")) and not is_indexable(_s(environment="development"))


def test_links_sent_to_users_use_the_configured_frontend(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "frontend_base_url", "https://moved.example")
    sent = []
    import app.api.v1.endpoints.auth as auth
    monkeypatch.setattr(auth, "send_plain_email", lambda to, subject, body: sent.append(body))
    r = client.post("/api/v1/auth/register", json={"email": "mover@example.com", "password": "correct-horse-battery", "organization_name": "M"})
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    client.post("/api/v1/auth/send-verification-email", headers=h)
    assert sent and "https://moved.example/verify-email?token=" in sent[0]
    assert "localhost" not in sent[0]


def test_no_source_file_hardcodes_a_product_domain():
    import pathlib, re
    root = pathlib.Path(__file__).resolve().parents[1] / "app"
    hits = [str(p) for p in root.rglob("*.py") if re.search(r"https?://[\w.-]*rankpilot\.(ai|com|io|app)", p.read_text())]
    assert hits == []
