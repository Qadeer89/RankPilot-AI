import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.db.session import get_db
from app.main import app

settings = get_settings()


@pytest.fixture(scope="session")
def engine():
    return create_engine(settings.database_url, future=True)


@pytest.fixture(autouse=True, scope="session")
def _ensure_clean_tables(engine):
    # Tests run inside a rolled-back transaction, but guard against leftovers
    # from a previous interrupted run.
    with engine.begin() as conn:
        conn.execute(
            text(
                "TRUNCATE audit_events, website_verifications, websites, "
                "memberships, organizations, users CASCADE"
            )
        )


@pytest.fixture
def db_session(engine):
    """Standard SQLAlchemy "join a session into an external transaction"
    recipe: the outer transaction is rolled back at teardown, so a
    `db.commit()` inside application code only releases a SAVEPOINT rather
    than persisting data across tests.
    """
    connection = engine.connect()
    outer_transaction = connection.begin()

    # autoflush=False matches app.db.session.SessionLocal: a test that
    # relied on autoflush to see its own uncommitted writes would pass here
    # but hit a real bug in production (see app/crawler/orchestrator.py
    # history for an example this caught).
    session_factory = sessionmaker(bind=connection, future=True, autoflush=False)
    session = session_factory()

    nested = connection.begin_nested()

    @event.listens_for(session, "after_transaction_end")
    def _restart_savepoint(sess, transaction):
        nonlocal nested
        if not nested.is_active:
            nested = connection.begin_nested()

    yield session

    session.close()
    outer_transaction.rollback()
    connection.close()


@pytest.fixture(autouse=True)
def _disable_auth_rate_limiting(monkeypatch):
    # The real limiter is Redis-backed and keyed by client IP -- every
    # TestClient request reports the same IP, so without this, tests
    # that call /auth/register or /auth/login more than a handful of
    # times (most of this suite does) would start 429ing each other.
    # test_auth_rate_limit.py re-enables the real function to test the
    # limiter itself.
    import app.api.v1.endpoints.auth as auth_module

    monkeypatch.setattr(auth_module, "rate_limit_by_ip", lambda *a, **k: None)


@pytest.fixture
def client(db_session):
    def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
