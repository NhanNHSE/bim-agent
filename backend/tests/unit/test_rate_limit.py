"""Rate limiting: shared limiter (src/core/rate_limit.py) and its use on /chat and IFC endpoints.

The autouse `_isolated_rate_limiter` fixture (conftest) forces the in-memory backend
and clears counters between tests. The Redis backend is covered in tests/integration.
"""

from unittest.mock import patch

import pytest
from fastapi import HTTPException

from src.core import rate_limit

REFLECTION = {"confidence": 0.9, "scores": {}, "feedback": "ok", "should_retry": False}


class TestLimiter:
    def test_allows_up_to_limit_then_429(self):
        for _ in range(3):
            rate_limit.hit("k", 3, 60)
        with pytest.raises(HTTPException) as exc:
            rate_limit.hit("k", 3, 60)
        assert exc.value.status_code == 429
        assert exc.value.headers["Retry-After"] == "60"
        assert exc.value.detail == "Quá nhiều yêu cầu. Thử lại sau 1 phút."

    def test_keys_are_independent(self):
        rate_limit.hit("a", 1, 60)
        rate_limit.hit("b", 1, 60)  # different key: still allowed
        with pytest.raises(HTTPException):
            rate_limit.hit("a", 1, 60)

    def test_window_expires(self, monkeypatch):
        clock = [1000.0]
        monkeypatch.setattr("src.core.rate_limit.time.time", lambda: clock[0])
        rate_limit.hit("w", 1, 30)
        clock[0] += 10
        with pytest.raises(HTTPException) as exc:
            rate_limit.hit("w", 1, 30)
        assert exc.value.headers["Retry-After"] == "20"
        assert exc.value.detail == "Quá nhiều yêu cầu. Thử lại sau 20 giây."
        clock[0] += 21  # first hit is now outside the 30 s window
        rate_limit.hit("w", 1, 30)


def _fresh_answer(**kwargs):
    return iter(["ok"]), [], {}


class TestChatRateLimit:
    @pytest.fixture(autouse=True)
    def _simple_mode(self, monkeypatch):
        monkeypatch.setattr("src.api.router_chat.settings.agent_mode", "simple")

    def _ask(self, client, headers):
        return client.post("/api/v1/chat", json={"message": "Yêu cầu PCCC?"}, headers=headers)

    def test_per_minute_limit_blocks_before_llm(self, client, auth_headers, monkeypatch):
        monkeypatch.setattr("src.api.router_chat.settings.chat_rate_limit_per_minute", 2)
        with patch("src.rag.graph_rag.ask", side_effect=_fresh_answer) as mock_ask, \
             patch("src.rag.reflection.evaluate_response", return_value=REFLECTION):
            assert self._ask(client, auth_headers).status_code == 200
            assert self._ask(client, auth_headers).status_code == 200
            blocked = self._ask(client, auth_headers)

        assert blocked.status_code == 429
        assert "Retry-After" in blocked.headers
        assert mock_ask.call_count == 2  # the blocked request never reached the LLM pipeline

    def test_limit_is_per_user(self, client, auth_headers, monkeypatch):
        monkeypatch.setattr("src.api.router_chat.settings.chat_rate_limit_per_minute", 1)
        other = client.post("/api/v1/auth/register", json={
            "email": "other@bim.vn", "full_name": "Other User",
            "password": "Pass@1234", "role": "engineer",
        })
        other_headers = {"Authorization": f"Bearer {other.json()['access_token']}"}

        with patch("src.rag.graph_rag.ask", side_effect=_fresh_answer), \
             patch("src.rag.reflection.evaluate_response", return_value=REFLECTION):
            assert self._ask(client, auth_headers).status_code == 200
            assert self._ask(client, auth_headers).status_code == 429
            assert self._ask(client, other_headers).status_code == 200

    def test_daily_quota(self, client, auth_headers, monkeypatch):
        monkeypatch.setattr("src.api.router_chat.settings.chat_rate_limit_per_minute", 100)
        monkeypatch.setattr("src.api.router_chat.settings.chat_rate_limit_per_day", 1)
        with patch("src.rag.graph_rag.ask", side_effect=_fresh_answer), \
             patch("src.rag.reflection.evaluate_response", return_value=REFLECTION):
            assert self._ask(client, auth_headers).status_code == 200
            blocked = self._ask(client, auth_headers)
        assert blocked.status_code == 429
        assert blocked.json()["detail"] == "Quá nhiều yêu cầu. Thử lại sau 24 giờ."


class TestIFCRateLimit:
    @pytest.fixture(autouse=True)
    def _limit_one(self, monkeypatch):
        monkeypatch.setattr("src.api.router_ifc.settings.ifc_rate_limit_per_minute", 1)

    def test_design_limited(self, client, auth_headers):
        # Empty description is rejected (400) but still counts against the limit
        assert client.post("/api/v1/ifc/design", json={}, headers=auth_headers).status_code == 400
        assert client.post("/api/v1/ifc/design", json={}, headers=auth_headers).status_code == 429

    def test_upload_limited(self, client, auth_headers):
        files = {"file": ("../evil.ifc", b"ISO-10303-21;", "application/octet-stream")}
        assert client.post("/api/v1/ifc/upload", files=files, headers=auth_headers).status_code == 400
        assert client.post("/api/v1/ifc/upload", files=files, headers=auth_headers).status_code == 429
