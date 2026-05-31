"""Shared test fixtures for BIM AI Agent.

Uses SQLite in-memory database for isolation — no PostgreSQL, Neo4j, or Qdrant needed.
"""

import os
import sys
import pytest
from unittest.mock import MagicMock, patch

# Add backend source to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Override env vars BEFORE importing any app modules
os.environ["DATABASE_URL"] = "sqlite:///./test.db"
os.environ["JWT_SECRET_KEY"] = "test-secret-key-for-testing-only"
os.environ["GEMINI_API_KEY"] = "test-key"
os.environ["NEO4J_URI"] = "bolt://localhost:7687"
os.environ["NEO4J_USER"] = "neo4j"
os.environ["NEO4J_PASSWORD"] = "test"
os.environ["QDRANT_HOST"] = "localhost"
os.environ["AGENT_MODE"] = "simple"  # Use simple mode for tests (no LLM calls)

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from src.database.models import Base
from src.database.session import get_db


# SQLite in-memory engine — shared across threads for TestClient
_test_engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

# Enable foreign keys for SQLite
@event.listens_for(_test_engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()

TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_test_engine)


def _override_get_db():
    """Override get_db to use test database."""
    db = TestSessionLocal()
    try:
        yield db
    finally:
        db.close()


# Suppress rate limiter for tests
_rate_limit_patched = False


@pytest.fixture(scope="session", autouse=True)
def setup_tables():
    """Create tables once per session."""
    Base.metadata.create_all(bind=_test_engine)
    yield
    Base.metadata.drop_all(bind=_test_engine)


@pytest.fixture(autouse=True)
def clean_tables():
    """Clean all data after each test."""
    yield
    db = TestSessionLocal()
    try:
        for table in reversed(Base.metadata.sorted_tables):
            db.execute(table.delete())
        db.commit()
    finally:
        db.close()


@pytest.fixture
def db_session():
    """Get a test database session."""
    db = TestSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def client():
    """FastAPI TestClient with mocked external dependencies."""
    # Patch init_db so it doesn't try to connect to real PostgreSQL
    with patch("src.main.init_db"):
        with patch("src.embeddings.embedding_service.get_model", return_value=MagicMock()):
            from src.main import app

            # Override DB dependency
            app.dependency_overrides[get_db] = _override_get_db

            # Ensure tables exist
            Base.metadata.create_all(bind=_test_engine)

            # Patch rate limiter to be a no-op in tests
            with patch("src.api.router_auth._check_rate_limit", return_value=None):
                with TestClient(app) as c:
                    yield c

            app.dependency_overrides.clear()


@pytest.fixture
def auth_headers(client):
    """Register + login a test user, return Authorization headers."""
    # Register
    reg_res = client.post("/api/v1/auth/register", json={
        "email": "test@bim.vn",
        "full_name": "Test User",
        "password": "Test@12345",
        "role": "engineer",
    })
    assert reg_res.status_code == 200, f"Register failed: {reg_res.json()}"

    token = reg_res.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def auth_headers_admin(client):
    """Register + login an admin user, return Authorization headers."""
    reg_res = client.post("/api/v1/auth/register", json={
        "email": "admin@bim.vn",
        "full_name": "Admin User",
        "password": "Admin@12345",
        "role": "admin",
    })
    assert reg_res.status_code == 200, f"Admin register failed: {reg_res.json()}"

    token = reg_res.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
