"""Additional unit tests for task 014 review fixes."""

import pytest
from fastapi import HTTPException

from src.api import router_ifc
from src.core.security import create_access_token, create_download_token, decode_download_token


def test_geometry_route_registered_on_ifc_router():
    """Verify GET /api/v1/ifc/geometry/{filename} is registered once on router_ifc.router."""
    routes = [
        r
        for r in router_ifc.router.routes
        if getattr(r, "path", "") == "/api/v1/ifc/geometry/{filename}" and "GET" in r.methods
    ]
    assert len(routes) == 1


def test_decode_download_token_rejects_access_token():
    """Regular access tokens without download scope cannot be used as download tokens."""
    access = create_access_token({"sub": "1", "username": "u", "role": "engineer"})
    with pytest.raises(HTTPException) as exc:
        decode_download_token(access, "house.ifc")
    assert exc.value.status_code == 401


def test_create_download_token_custom_ttl():
    """Verify custom ttl_seconds works with decode_download_token."""
    token = create_download_token("42", "sample.ifc", ttl_seconds=120)
    payload = decode_download_token(token, "sample.ifc")
    assert payload["sub"] == "42"
    assert payload["file"] == "sample.ifc"
