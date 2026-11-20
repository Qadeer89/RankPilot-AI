from app.config import Settings


def test_an_empty_environment_variable_does_not_override_the_env_file(tmp_path, monkeypatch):
    """Regression for the live deploy: pm2 injected RANKPILOT_GOOGLE_CLIENT_ID="" into the worker, which hid the value in .env."""
    env_file = tmp_path / ".env"
    env_file.write_text("RANKPILOT_GOOGLE_CLIENT_ID=from-dotenv\nRANKPILOT_GOOGLE_CLIENT_SECRET=secret-from-dotenv\n")
    monkeypatch.setenv("RANKPILOT_GOOGLE_CLIENT_ID", "")
    monkeypatch.setenv("RANKPILOT_GOOGLE_CLIENT_SECRET", "")
    s = Settings(_env_file=str(env_file))
    assert s.google_client_id == "from-dotenv" and s.google_client_secret == "secret-from-dotenv"


def test_a_real_environment_variable_still_wins_over_the_env_file(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("RANKPILOT_GOOGLE_CLIENT_ID=from-dotenv\n")
    monkeypatch.setenv("RANKPILOT_GOOGLE_CLIENT_ID", "from-environment")
    assert Settings(_env_file=str(env_file)).google_client_id == "from-environment"
