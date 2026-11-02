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

    session_factory = sessionmaker(bind=connection, future=True)
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


@pytest.fixture
def client(db_session):
    def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
