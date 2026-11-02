import pytest

from app.config import DEFAULT_JWT_SECRET, Settings


def test_production_with_default_jwt_secret_is_refused():
    with pytest.raises(ValueError, match="RANKPILOT_JWT_SECRET"):
        Settings(environment="production", jwt_secret=DEFAULT_JWT_SECRET)


def test_production_with_real_jwt_secret_is_accepted():
    settings = Settings(environment="production", jwt_secret="a-real-unique-secret")
    assert settings.jwt_secret == "a-real-unique-secret"


def test_development_with_default_jwt_secret_is_accepted():
    settings = Settings(environment="development", jwt_secret=DEFAULT_JWT_SECRET)
    assert settings.jwt_secret == DEFAULT_JWT_SECRET
