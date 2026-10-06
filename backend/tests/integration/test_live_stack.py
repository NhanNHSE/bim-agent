"""Smoke checks that every backing service is reachable and wired correctly."""


class TestServices:
    """Each datastore answers with the configuration the app actually uses."""

    def test_health_reports_neo4j_connected(self, api):
        res = api.get("/api/v1/health")
        assert res.status_code == 200
        body = res.json()
        assert body["services"]["neo4j"] == "connected", body
        assert body["status"] == "healthy", body

    def test_neo4j_query_roundtrip(self):
        from src.knowledge_graph.neo4j_client import run_query
        assert run_query("RETURN 1 AS ok") == [{"ok": 1}]

    def test_qdrant_reachable(self):
        from src.embeddings.vector_store import get_client
        collections = get_client().get_collections().collections
        assert isinstance(collections, list)

    def test_redis_ping(self):
        import redis
        from src.core.config import get_settings
        settings = get_settings()
        client = redis.Redis(host=settings.redis_host, port=settings.redis_port, socket_connect_timeout=5)
        assert client.ping() is True


class TestAuthOnPostgres:
    """Auth flow persisted in the real PostgreSQL database."""

    def test_login_and_profile(self, api, engineer):
        email, password, _ = engineer
        login = api.post("/api/v1/auth/login", json={"email": email, "password": password})
        assert login.status_code == 200, login.text

        token = login.json()["access_token"]
        me = api.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert me.status_code == 200
        assert me.json()["email"] == email
        assert me.json()["role"] == "engineer"

    def test_new_user_has_no_conversations(self, api, engineer):
        _, _, headers = engineer
        res = api.get("/api/v1/conversations", headers=headers)
        assert res.status_code == 200
        assert res.json() == []

    def test_admin_self_registration_rejected(self, api):
        res = api.post("/api/v1/auth/register", json={
            "email": "it-escalation@bim.vn",
            "full_name": "Escalation Attempt",
            "password": "Integr@tion123",
            "role": "admin",
        })
        assert res.status_code == 403
