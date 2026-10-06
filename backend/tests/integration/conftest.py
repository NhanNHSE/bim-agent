"""Integration tests run inside the backend container against the live Docker stack
(PostgreSQL, Neo4j, Qdrant, Redis). Nothing is mocked here.

    docker exec -e BIM_INTEGRATION=1 bim-backend pytest tests/integration -v

Without BIM_INTEGRATION=1 every test in this directory is skipped, so a plain
`pytest tests` stays safe on a machine without the stack.
"""

import os
import uuid

import httpx
import pytest

API_URL = os.environ.get("BIM_API_URL", "http://localhost:8000")


@pytest.fixture(autouse=True)
def _require_stack():
    if os.environ.get("BIM_INTEGRATION") != "1":
        pytest.skip("needs the running Docker stack; set BIM_INTEGRATION=1")


@pytest.fixture(scope="module")
def api():
    with httpx.Client(base_url=API_URL, timeout=30) as client:
        yield client


@pytest.fixture(scope="module")
def engineer(api):
    """A freshly registered engineer: (email, password, auth headers).

    /register is rate limited to 5 per IP per 15 min (Redis), so tests share this account.
    """
    email = f"it-{uuid.uuid4().hex[:10]}@bim.vn"
    password = "Integr@tion123"
    res = api.post("/api/v1/auth/register", json={
        "email": email,
        "full_name": "Integration Engineer",
        "password": password,
        "role": "engineer",
    })
    assert res.status_code == 200, res.text
    token = res.json()["access_token"]
    return email, password, {"Authorization": f"Bearer {token}"}
