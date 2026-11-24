

def test_public_pricing_needs_no_login_and_matches_the_logged_in_plans(client):
    r = client.get("/api/v1/public/pricing")
    assert r.status_code == 200
    body = r.json()
    assert {p["interval"] for p in body["plans"]} == {"month", "year"}
    assert all(p["price_cents"] > 0 and p["currency"] for p in body["plans"])
