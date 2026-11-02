"""RP13-015: the OpenAI API key (and other server-side secrets) must
never reach the frontend, logs, or an API error response. These are
regression tests, not a one-off audit -- if a future change adds a new
place that reads `openai_api_key` or echoes an unhandled exception to
the client, one of these should fail.
"""

import pathlib

APP_DIR = pathlib.Path(__file__).resolve().parent.parent / "app"

# The only two files allowed to touch the raw key: the settings
# definition itself, and the one place that hands it to the OpenAI SDK.
ALLOWED_OPENAI_KEY_FILES = {"app/config.py", "app/ai/client.py"}


def test_openai_api_key_is_only_referenced_from_its_two_legitimate_call_sites():
    offenders = []
    for path in APP_DIR.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        relative = str(path.relative_to(APP_DIR.parent))
        if relative in ALLOWED_OPENAI_KEY_FILES:
            continue
        if "openai_api_key" in path.read_text():
            offenders.append(relative)

    assert offenders == [], f"openai_api_key referenced outside its allowed call sites: {offenders}"


def test_unhandled_exception_returns_a_generic_500_without_a_traceback():
    from fastapi.testclient import TestClient

    from app.db.session import get_db
    from app.main import app

    def broken_get_db():
        raise RuntimeError("boom: should never reach the response body")

    app.dependency_overrides[get_db] = broken_get_db
    try:
        # raise_server_exceptions=False mirrors how a real deployment
        # behaves (debug=False): the TestClient default instead re-raises
        # the exception into the test process for debugging, which would
        # make this test pass for the wrong reason.
        with TestClient(app, raise_server_exceptions=False) as plain_client:
            response = plain_client.get("/api/v1/ready")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 500
    assert "boom" not in response.text
    assert "Traceback" not in response.text


def test_fastapi_app_does_not_run_in_debug_mode():
    from app.main import app

    assert app.debug is False
