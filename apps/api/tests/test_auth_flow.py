def _register(client, email="owner@example.com", password="correct-horse-battery", org="Acme SEO"):
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "organization_name": org},
    )
    assert response.status_code == 201, response.text
    return response.json()["access_token"]


def _auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_register_then_me_returns_owner_membership(client):
    token = _register(client)

    response = client.get("/api/v1/me", headers=_auth_headers(token))
    assert response.status_code == 200
    body = response.json()
    assert body["user"]["email"] == "owner@example.com"
    assert len(body["organizations"]) == 1
    assert body["organizations"][0]["role"] == "owner"


def test_duplicate_email_registration_is_rejected(client):
    _register(client, email="dupe@example.com")

    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "dupe@example.com",
            "password": "another-password",
            "organization_name": "Other Org",
        },
    )
    assert response.status_code == 409


def test_login_with_wrong_password_is_rejected(client):
    _register(client, email="loginuser@example.com", password="correct-horse-battery")

    response = client.post(
        "/api/v1/auth/login",
        json={"email": "loginuser@example.com", "password": "wrong-password"},
    )
    assert response.status_code == 401


def test_me_without_credentials_is_unauthorized(client):
    response = client.get("/api/v1/me")
    assert response.status_code == 401
