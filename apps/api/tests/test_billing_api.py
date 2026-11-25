

def test_public_pricing_needs_no_login_and_publishes_nothing_until_a_plan_is_approved(client):
    r = client.get("/api/v1/public/pricing")
    assert r.status_code == 200
    body = r.json()
    assert body["plans"] == [] and body["pricing_finalized"] is False
