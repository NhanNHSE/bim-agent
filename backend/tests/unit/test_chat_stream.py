"""Tests for Chat SSE Streaming API (/api/v1/chat)."""

import json
from unittest.mock import patch
import pytest


def parse_sse(text: str) -> list[dict]:
    """Parse SSE response text into a list of parsed JSON data events."""
    events = []
    for block in text.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        for line in block.split("\n"):
            line = line.strip()
            if line.startswith("data: "):
                data_str = line[len("data: "):]
                try:
                    events.append(json.loads(data_str))
                except json.JSONDecodeError:
                    pass
    return events


@pytest.fixture
def sample_docs():
    """Sample documents fixture with metadata."""
    return [
        {
            "text": f"Nội dung {i}",
            "metadata": {
                "standard_code": "QCVN 06:2022/BXD",
                "article_number": str(i),
                "source": "vector",
            },
        }
        for i in range(6)
    ]


@pytest.fixture(autouse=True)
def default_agent_mode(monkeypatch):
    """Set AGENT_MODE to simple by default as per specifications."""
    monkeypatch.setattr("src.api.router_chat.settings.agent_mode", "simple")


@pytest.fixture(autouse=True)
def mock_evaluate_response():
    """Mock reflection evaluate_response to return default valid confidence."""
    with patch("src.rag.reflection.evaluate_response") as mock_eval:
        mock_eval.return_value = {
            "confidence": 0.9,
            "scores": {},
            "feedback": "ok",
            "should_retry": False,
        }
        yield mock_eval


class TestChatStream:
    """Test POST /api/v1/chat Server-Sent Events stream."""

    def test_chat_stream_success(self, client, auth_headers, sample_docs):
        """Successful stream with meta, chunk, done events, and persisted messages."""
        with patch("src.rag.graph_rag.ask") as mock_ask:
            mock_ask.return_value = (
                iter(["Xin ", "chào"]),
                sample_docs,
                {"topic": "PCCC"},
            )

            res = client.post(
                "/api/v1/chat",
                json={"message": "Yêu cầu PCCC?"},
                headers=auth_headers,
            )

            assert res.status_code == 200
            assert res.headers["content-type"].startswith("text/event-stream")

            events = parse_sse(res.text)
            assert len(events) >= 4

            # First event: meta
            meta = events[0]
            assert meta["type"] == "meta"
            assert isinstance(meta["conversation_id"], int)
            assert meta["entities"] == {"topic": "PCCC"}
            assert len(meta["citations"]) == 5
            assert meta["citations"][0]["standard_code"] == "QCVN 06:2022/BXD"
            assert meta["citations"][0]["article_number"] == "0"

            # Chunk events
            chunks = [e for e in events if e.get("type") == "chunk"]
            assert len(chunks) == 2
            assert chunks[0]["content"] == "Xin "
            assert chunks[1]["content"] == "chào"

            # Last event: done
            done = events[-1]
            assert done["type"] == "done"
            assert isinstance(done["message_id"], int)
            assert done["confidence"] == pytest.approx(0.9, abs=0.01)
            assert done["confidence_label"] == "Rất tin cậy"
            assert done["reflection_feedback"] == "ok"

            # Check messages persisted in conversation
            conv_id = meta["conversation_id"]
            get_res = client.get(
                f"/api/v1/conversations/{conv_id}/messages",
                headers=auth_headers,
            )
            assert get_res.status_code == 200
            messages = sorted(get_res.json(), key=lambda m: m["id"])
            assert len(messages) == 2
            assert messages[0]["role"] == "user"
            assert messages[0]["content"] == "Yêu cầu PCCC?"
            assert messages[1]["role"] == "assistant"
            assert messages[1]["content"] == "Xin chào"
            assert len(messages[1]["citations"]) == 5

    def test_chat_stream_error_mid_stream(self, client, auth_headers, sample_docs):
        """Error raised during streaming yields error event without done, saving only user message."""
        def faulty_stream():
            yield "Xin "
            raise RuntimeError("llm down")

        with patch("src.rag.graph_rag.ask") as mock_ask:
            mock_ask.return_value = (
                faulty_stream(),
                sample_docs,
                {"topic": "PCCC"},
            )

            res = client.post(
                "/api/v1/chat",
                json={"message": "Câu hỏi gây lỗi"},
                headers=auth_headers,
            )
            assert res.status_code == 200

            events = parse_sse(res.text)
            assert any(e.get("type") == "error" for e in events)
            assert all(e.get("type") != "done" for e in events)

            conv_id = events[0]["conversation_id"]
            get_res = client.get(
                f"/api/v1/conversations/{conv_id}/messages",
                headers=auth_headers,
            )
            assert get_res.status_code == 200
            messages = get_res.json()
            assert len(messages) == 1
            assert messages[0]["role"] == "user"

    def test_chat_stream_conversation_history(self, client, auth_headers, sample_docs):
        """Follow-up message in existing conversation passes previous user message to ask."""
        with patch("src.rag.graph_rag.ask") as mock_ask:
            # First turn
            mock_ask.return_value = (
                iter(["Xin ", "chào"]),
                sample_docs,
                {"topic": "PCCC"},
            )
            res1 = client.post(
                "/api/v1/chat",
                json={"message": "Câu hỏi turn 1"},
                headers=auth_headers,
            )
            assert res1.status_code == 200
            events1 = parse_sse(res1.text)
            conv_id = events1[0]["conversation_id"]

            # Second turn with conversation_id
            mock_ask.return_value = (
                iter(["Tiếp ", "tục"]),
                sample_docs,
                {"topic": "PCCC"},
            )
            res2 = client.post(
                "/api/v1/chat",
                json={"message": "Câu hỏi turn 2", "conversation_id": conv_id},
                headers=auth_headers,
            )
            assert res2.status_code == 200

            history = mock_ask.call_args.kwargs["messages"]
            assert any(
                m.get("role") == "user" and m.get("content") == "Câu hỏi turn 1"
                for m in history
            )

    def test_chat_stream_forbidden_other_user_conversation(self, client, auth_headers, sample_docs):
        """User B cannot access or send messages to User A's conversation (returns 404, ask not called)."""
        with patch("src.rag.graph_rag.ask") as mock_ask:
            mock_ask.return_value = (iter(["Xin chào"]), sample_docs, {})

            # User A creates a conversation
            res_a = client.post(
                "/api/v1/chat",
                json={"message": "Hội thoại bí mật của A"},
                headers=auth_headers,
            )
            assert res_a.status_code == 200
            conv_id_a = parse_sse(res_a.text)[0]["conversation_id"]

            # Register User B
            reg_b = client.post(
                "/api/v1/auth/register",
                json={
                    "email": "user_b_engineer@bim.vn",
                    "full_name": "User B",
                    "password": "Password@123",
                    "role": "engineer",
                },
            )
            assert reg_b.status_code == 200
            token_b = reg_b.json()["access_token"]
            headers_b = {"Authorization": f"Bearer {token_b}"}

            mock_ask.reset_mock()

            # User B attempts to send message to User A's conversation
            res_b = client.post(
                "/api/v1/chat",
                json={"message": "Xem trộm", "conversation_id": conv_id_a},
                headers=headers_b,
            )
            assert res_b.status_code == 404
            mock_ask.assert_not_called()

    def test_chat_stream_unauthorized(self, client):
        """Request without authentication token returns 401 or 403."""
        res = client.post("/api/v1/chat", json={"message": "Chào"})
        assert res.status_code in (401, 403)

    def test_chat_stream_multi_agent_design_result(self, client, auth_headers, monkeypatch):
        """multi_agent mode returns 4-tuple coordinator results including design metadata in meta event."""
        monkeypatch.setattr("src.api.router_chat.settings.agent_mode", "multi_agent")
        design_payload = {
            "design": {
                "filename": "nha.ifc",
                "spec": {"num_storeys": 3},
                "violations": [],
                "structure_type": "building",
            }
        }
        with patch("src.agents.coordinator.ask") as mock_coord_ask:
            mock_coord_ask.return_value = (
                iter(["ok"]),
                [],
                {},
                design_payload,
            )

            res = client.post(
                "/api/v1/chat",
                json={"message": "Thiết kế nhà 3 tầng", "mode": "design"},
                headers=auth_headers,
            )
            assert res.status_code == 200

            events = parse_sse(res.text)
            assert len(events) >= 1
            meta = events[0]
            assert meta["type"] == "meta"
            assert "design" in meta
            assert meta["design"]["filename"] == "nha.ifc"
            assert meta["design"]["spec"]["structure_type"] == "building"
            assert meta["design"]["structure_type"] == "building"
