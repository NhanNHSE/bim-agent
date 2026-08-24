"""Tests for Chat API — Conversations, Messages, and Feedback."""

import pytest


class TestConversations:
    """Test conversation CRUD."""

    def test_list_conversations_empty(self, client, auth_headers):
        res = client.get("/api/v1/conversations", headers=auth_headers)
        assert res.status_code == 200
        assert res.json() == []

    def test_list_conversations_requires_auth(self, client):
        res = client.get("/api/v1/conversations")
        assert res.status_code in (401, 403)


class TestDeleteConversation:
    """Test conversation deletion."""

    def test_delete_nonexistent(self, client, auth_headers):
        res = client.delete("/api/v1/conversations/9999", headers=auth_headers)
        assert res.status_code == 404

    def test_delete_requires_auth(self, client):
        res = client.delete("/api/v1/conversations/1")
        assert res.status_code in (401, 403)


class TestMessages:
    """Test message retrieval."""

    def test_get_messages_nonexistent_conversation(self, client, auth_headers):
        res = client.get("/api/v1/conversations/9999/messages", headers=auth_headers)
        assert res.status_code == 404

    def test_get_messages_requires_auth(self, client):
        res = client.get("/api/v1/conversations/1/messages")
        assert res.status_code in (401, 403)


class TestFeedback:
    """Test message feedback (like/dislike)."""

    def _create_conversation_with_message(self, db_session):
        """Helper: create a conversation + assistant message directly in DB."""
        from src.database.models import Conversation, Message, User
        from src.core.security import hash_password

        # Create user
        user = User(
            email="fb@bim.vn",
            full_name="Feedback Tester",
            hashed_password=hash_password("Test@123"),
            role="engineer",
        )
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)

        # Create conversation
        conv = Conversation(user_id=user.id, title="Test Conversation")
        db_session.add(conv)
        db_session.commit()
        db_session.refresh(conv)

        # Create assistant message
        msg = Message(
            conversation_id=conv.id,
            role="assistant",
            content="Đây là câu trả lời test.",
        )
        db_session.add(msg)
        db_session.commit()
        db_session.refresh(msg)

        return user, conv, msg

    def test_set_feedback_like(self, client, db_session):
        user, conv, msg = self._create_conversation_with_message(db_session)

        # Login as this user
        from src.core.security import create_access_token
        token = create_access_token({"sub": str(user.id), "role": user.role})
        headers = {"Authorization": f"Bearer {token}"}

        res = client.put(
            f"/api/v1/messages/{msg.id}/feedback",
            json={"feedback": "like"},
            headers=headers,
        )
        assert res.status_code == 200
        assert res.json()["feedback"] == "like"
        assert res.json()["message_id"] == msg.id

    def test_feedback_toggle(self, client, db_session):
        """Clicking same feedback twice should clear it."""
        user, conv, msg = self._create_conversation_with_message(db_session)

        from src.core.security import create_access_token
        token = create_access_token({"sub": str(user.id), "role": user.role})
        headers = {"Authorization": f"Bearer {token}"}

        # First click: like
        res1 = client.put(
            f"/api/v1/messages/{msg.id}/feedback",
            json={"feedback": "like"},
            headers=headers,
        )
        assert res1.json()["feedback"] == "like"

        # Second click: like again → should clear
        res2 = client.put(
            f"/api/v1/messages/{msg.id}/feedback",
            json={"feedback": "like"},
            headers=headers,
        )
        assert res2.json()["feedback"] is None

    def test_feedback_switch(self, client, db_session):
        """Switch from like to dislike."""
        user, conv, msg = self._create_conversation_with_message(db_session)

        from src.core.security import create_access_token
        token = create_access_token({"sub": str(user.id), "role": user.role})
        headers = {"Authorization": f"Bearer {token}"}

        # Like
        client.put(f"/api/v1/messages/{msg.id}/feedback",
                    json={"feedback": "like"}, headers=headers)

        # Switch to dislike
        res = client.put(f"/api/v1/messages/{msg.id}/feedback",
                         json={"feedback": "dislike"}, headers=headers)
        assert res.json()["feedback"] == "dislike"

    def test_feedback_invalid_value(self, client, auth_headers):
        res = client.put(
            "/api/v1/messages/1/feedback",
            json={"feedback": "love"},
            headers=auth_headers,
        )
        assert res.status_code == 400

    def test_feedback_nonexistent_message(self, client, auth_headers):
        res = client.put(
            "/api/v1/messages/9999/feedback",
            json={"feedback": "like"},
            headers=auth_headers,
        )
        assert res.status_code == 404

    def test_feedback_requires_auth(self, client):
        res = client.put("/api/v1/messages/1/feedback", json={"feedback": "like"})
        assert res.status_code in (401, 403)
