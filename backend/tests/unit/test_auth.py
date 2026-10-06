"""Tests for Authentication API (/api/v1/auth)."""

import pytest


class TestRegister:
    """Test user registration."""

    def test_register_success(self, client):
        res = client.post("/api/v1/auth/register", json={
            "email": "new@bim.vn",
            "full_name": "New User",
            "password": "Secure@123",
            "role": "engineer",
        })
        assert res.status_code == 200
        data = res.json()
        assert "access_token" in data
        assert data["user"]["email"] == "new@bim.vn"
        assert data["user"]["full_name"] == "New User"
        assert data["user"]["role"] == "engineer"

    def test_register_duplicate_email(self, client):
        # First register
        client.post("/api/v1/auth/register", json={
            "email": "dup@bim.vn",
            "full_name": "First User",
            "password": "Pass@123",
        })
        # Duplicate
        res = client.post("/api/v1/auth/register", json={
            "email": "dup@bim.vn",
            "full_name": "Second User",
            "password": "Pass@456",
        })
        assert res.status_code == 400
        assert "đã được đăng ký" in res.json()["detail"]

    def test_register_invalid_role(self, client):
        res = client.post("/api/v1/auth/register", json={
            "email": "role@bim.vn",
            "full_name": "Bad Role",
            "password": "Pass@123",
            "role": "superadmin",
        })
        assert res.status_code == 400

    @pytest.mark.parametrize("role", ["admin", "project_manager"])
    def test_register_privileged_role_forbidden(self, client, role):
        """Privilege escalation regression: privileged roles cannot be self-assigned."""
        res = client.post("/api/v1/auth/register", json={
            "email": f"{role}@bim.vn",
            "full_name": "Escalation Attempt",
            "password": "Pass@1234",
            "role": role,
        })
        assert res.status_code == 403

        login = client.post("/api/v1/auth/login", json={
            "email": f"{role}@bim.vn",
            "password": "Pass@1234",
        })
        assert login.status_code == 401  # no account was created

    def test_register_viewer_allowed(self, client):
        res = client.post("/api/v1/auth/register", json={
            "email": "viewer@bim.vn",
            "full_name": "Viewer User",
            "password": "Pass@1234",
            "role": "viewer",
        })
        assert res.status_code == 200
        assert res.json()["user"]["role"] == "viewer"

    def test_register_invalid_email(self, client):
        res = client.post("/api/v1/auth/register", json={
            "email": "not-an-email",
            "full_name": "Bad Email",
            "password": "Pass@123",
        })
        assert res.status_code == 422  # Validation error


class TestLogin:
    """Test user login."""

    def test_login_success(self, client):
        # Register first
        client.post("/api/v1/auth/register", json={
            "email": "login@bim.vn",
            "full_name": "Login User",
            "password": "Login@123",
        })
        # Login
        res = client.post("/api/v1/auth/login", json={
            "email": "login@bim.vn",
            "password": "Login@123",
        })
        assert res.status_code == 200
        data = res.json()
        assert "access_token" in data
        assert data["user"]["email"] == "login@bim.vn"

    def test_login_wrong_password(self, client):
        client.post("/api/v1/auth/register", json={
            "email": "wrong@bim.vn",
            "full_name": "Wrong Pass",
            "password": "Correct@123",
        })
        res = client.post("/api/v1/auth/login", json={
            "email": "wrong@bim.vn",
            "password": "Wrong@123",
        })
        assert res.status_code == 401

    def test_login_nonexistent_user(self, client):
        res = client.post("/api/v1/auth/login", json={
            "email": "ghost@bim.vn",
            "password": "Ghost@123",
        })
        assert res.status_code == 401


class TestProfile:
    """Test profile endpoint."""

    def test_get_profile_authenticated(self, client, auth_headers):
        res = client.get("/api/v1/auth/me", headers=auth_headers)
        assert res.status_code == 200
        data = res.json()
        assert data["email"] == "test@bim.vn"
        assert data["role"] == "engineer"

    def test_get_profile_no_token(self, client):
        res = client.get("/api/v1/auth/me")
        assert res.status_code in (401, 403)

    def test_get_profile_invalid_token(self, client):
        res = client.get("/api/v1/auth/me", headers={
            "Authorization": "Bearer invalid-token-here"
        })
        assert res.status_code in (401, 403)
