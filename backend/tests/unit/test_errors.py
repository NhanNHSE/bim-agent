"""Tests for the single application error module (src/core/errors.py)."""

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from src.core.errors import (
    APIError,
    ForbiddenError,
    NotFoundError,
    RateLimitError,
    register_error_handlers,
)


@pytest.fixture
def app_client():
    app = FastAPI()
    register_error_handlers(app)

    @app.get("/missing")
    def missing():
        raise NotFoundError("Mô hình IFC", detail="a.ifc")

    @app.get("/forbidden")
    def forbidden():
        raise ForbiddenError()

    @app.get("/limited")
    def limited():
        raise RateLimitError(retry_after=600)

    @app.get("/custom")
    def custom():
        raise APIError(422, "IFC_INVALID", "File IFC không hợp lệ")

    @app.get("/http")
    def http():
        raise HTTPException(404, "Cuộc hội thoại không tồn tại")

    return TestClient(app)


class TestAPIErrorHandler:
    def test_not_found_with_detail(self, app_client):
        res = app_client.get("/missing")
        assert res.status_code == 404
        assert res.json() == {"error": {
            "code": "NOT_FOUND",
            "message": "Mô hình IFC không tồn tại",
            "detail": "a.ifc",
        }}

    def test_forbidden(self, app_client):
        res = app_client.get("/forbidden")
        assert res.status_code == 403
        assert res.json()["error"]["code"] == "FORBIDDEN"
        assert "detail" not in res.json()["error"]

    def test_rate_limit_message(self, app_client):
        res = app_client.get("/limited")
        assert res.status_code == 429
        assert res.json()["error"]["message"] == "Quá nhiều yêu cầu. Thử lại sau 10 phút."

    def test_custom_code(self, app_client):
        res = app_client.get("/custom")
        assert res.status_code == 422
        assert res.json()["error"]["code"] == "IFC_INVALID"

    def test_http_exception_untouched(self, app_client):
        """Existing endpoints raise HTTPException; its {"detail": ...} shape must not change."""
        res = app_client.get("/http")
        assert res.status_code == 404
        assert res.json() == {"detail": "Cuộc hội thoại không tồn tại"}
