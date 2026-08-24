"""Security tests — validate auth hardening, Cypher safety, and path traversal protection."""

import pytest
from unittest.mock import patch, MagicMock
from pydantic import ValidationError


# ===== Password Validation Tests =====

class TestPasswordValidation:
    """Test password strength requirements in RegisterRequest."""

    def _make_request(self, **overrides):
        from src.api.router_auth import RegisterRequest
        defaults = {
            "email": "test@example.com",
            "full_name": "Test User",
            "password": "StrongPass1",
            "role": "engineer",
        }
        defaults.update(overrides)
        return RegisterRequest(**defaults)

    def test_valid_password(self):
        """Strong password should pass validation."""
        req = self._make_request(password="MyStr0ngP@ss")
        assert req.password == "MyStr0ngP@ss"

    def test_password_too_short(self):
        """Passwords under 8 characters should be rejected."""
        with pytest.raises(ValidationError, match="ít nhất 8 ký tự"):
            self._make_request(password="Short1A")

    def test_password_too_long(self):
        """Passwords over 128 characters should be rejected."""
        with pytest.raises(ValidationError, match="quá 128"):
            self._make_request(password="A1" + "a" * 127)

    def test_password_no_uppercase(self):
        """Passwords without uppercase letters should be rejected."""
        with pytest.raises(ValidationError, match="chữ hoa"):
            self._make_request(password="alllowercase1")

    def test_password_no_lowercase(self):
        """Passwords without lowercase letters should be rejected."""
        with pytest.raises(ValidationError, match="chữ thường"):
            self._make_request(password="ALLUPPERCASE1")

    def test_password_no_digit(self):
        """Passwords without digits should be rejected."""
        with pytest.raises(ValidationError, match="chữ số"):
            self._make_request(password="NoDigitsHere")

    def test_empty_password(self):
        """Empty passwords should be rejected."""
        with pytest.raises(ValidationError):
            self._make_request(password="")

    def test_full_name_stripped(self):
        """Full name should be stripped of whitespace."""
        req = self._make_request(full_name="  Test User  ")
        assert req.full_name == "Test User"

    def test_full_name_too_short(self):
        """Names under 2 characters should be rejected."""
        with pytest.raises(ValidationError, match="ít nhất 2"):
            self._make_request(full_name="A")


# ===== Cypher Validation Tests =====

class TestCypherValidation:
    """Test the whitelist-based Cypher query validation."""

    def _validate(self, query: str):
        from src.knowledge_graph.graph_query_generator import _validate_cypher
        return _validate_cypher(query)

    # --- Safe queries that should pass ---
    def test_basic_match(self):
        ok, _ = self._validate("MATCH (n:Standard) RETURN n")
        assert ok

    def test_match_with_where(self):
        ok, _ = self._validate(
            "MATCH (n:Article) WHERE n.title CONTAINS 'PCCC' RETURN n.title"
        )
        assert ok

    def test_optional_match(self):
        ok, _ = self._validate(
            "OPTIONAL MATCH (s:Standard)-[:CONTAINS]->(c:Chapter) RETURN s, c"
        )
        assert ok

    def test_with_clause(self):
        ok, _ = self._validate(
            "MATCH (n) WITH n LIMIT 10 RETURN count(n)"
        )
        assert ok

    def test_unwind(self):
        ok, _ = self._validate(
            "UNWIND ['a', 'b'] AS x MATCH (n {name: x}) RETURN n"
        )
        assert ok

    # --- Dangerous queries that must be blocked ---
    def test_block_delete(self):
        ok, reason = self._validate("MATCH (n) DELETE n RETURN n")
        assert not ok
        assert "DELETE" in reason

    def test_block_detach_delete(self):
        ok, reason = self._validate("MATCH (n) DETACH DELETE n RETURN n")
        assert not ok
        assert "DETACH" in reason or "DELETE" in reason

    def test_block_create(self):
        ok, reason = self._validate("CREATE (n:Malicious) RETURN n")
        assert not ok

    def test_block_merge(self):
        ok, reason = self._validate("MERGE (n:Malicious) RETURN n")
        assert not ok

    def test_block_set(self):
        ok, reason = self._validate("MATCH (n) SET n.hacked = true RETURN n")
        assert not ok
        assert "SET" in reason

    def test_block_remove(self):
        ok, reason = self._validate("MATCH (n) REMOVE n.name RETURN n")
        assert not ok

    def test_block_drop(self):
        ok, reason = self._validate("MATCH (n) DROP n RETURN n")
        assert not ok

    def test_block_apoc(self):
        """APOC procedures should be blocked (case insensitive)."""
        ok, reason = self._validate("MATCH (n) WHERE APOC.text.clean(n.name) RETURN n")
        assert not ok
        assert "APOC" in reason

    def test_block_apoc_case_bypass(self):
        """Even lowercase APOC should be blocked."""
        ok, reason = self._validate("MATCH (n) WHERE apoc.text.clean(n.name) RETURN n")
        assert not ok

    def test_block_load_csv(self):
        ok, reason = self._validate("LOAD CSV FROM 'http://evil.com/data.csv' AS row RETURN row")
        assert not ok

    def test_block_semicolon_injection(self):
        """Semicolons for multi-statement injection must be blocked."""
        ok, reason = self._validate("MATCH (n) RETURN n; MATCH (m) DELETE m")
        assert not ok
        assert "Semicolon" in reason

    def test_block_empty_query(self):
        ok, _ = self._validate("")
        assert not ok

    def test_block_no_return(self):
        """Queries without RETURN should be blocked."""
        ok, reason = self._validate("MATCH (n:Standard)")
        assert not ok
        assert "RETURN" in reason

    def test_block_too_long(self):
        """Excessively long queries should be blocked."""
        long_query = "MATCH (n) " + "WHERE n.x = 'a' " * 200 + "RETURN n"
        ok, reason = self._validate(long_query)
        assert not ok
        assert "too long" in reason

    def test_must_start_with_safe_keyword(self):
        """Queries starting with unsafe keywords should be blocked."""
        ok, reason = self._validate("CALL dbms.security.listUsers() YIELD username RETURN username")
        assert not ok


# ===== Path Traversal Tests =====

class TestPathTraversal:
    """Test filename sanitization in IFC router."""

    def _safe(self, filename: str):
        import sys
        # Mock heavy dependencies that router_ifc imports transitively
        mock = MagicMock()
        for mod in [
            "fastembed", "qdrant_client", "qdrant_client.models",
            "qdrant_client.http", "qdrant_client.http.models",
        ]:
            if mod not in sys.modules:
                sys.modules[mod] = mock
        from src.api.router_ifc import _safe_filename
        return _safe_filename(filename)

    def test_normal_filename(self):
        assert self._safe("building_001.ifc") == "building_001.ifc"

    def test_directory_traversal(self):
        """../../../etc/passwd should be rejected."""
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            self._safe("../../../etc/passwd")
        assert exc_info.value.status_code == 400

    def test_absolute_path(self):
        """Absolute paths should be rejected."""
        from fastapi import HTTPException
        with pytest.raises(HTTPException):
            self._safe("/etc/passwd")

    def test_windows_path(self):
        """Windows-style paths should be rejected."""
        from fastapi import HTTPException
        with pytest.raises(HTTPException):
            self._safe("C:\\Windows\\system32\\config.ifc")

    def test_wrong_extension(self):
        """Non-IFC files should be rejected."""
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            self._safe("malicious.py")
        assert exc_info.value.status_code == 400

    def test_hidden_file(self):
        """Hidden files (starting with .) should be rejected."""
        from fastapi import HTTPException
        with pytest.raises(HTTPException):
            self._safe(".secret.ifc")

    def test_empty_filename(self):
        from fastapi import HTTPException
        with pytest.raises(HTTPException):
            self._safe("")


# ===== Config Validation Tests =====

class TestConfigValidation:
    """Test startup validation of security-critical configuration."""

    def test_weak_jwt_warning(self):
        """Weak JWT secret should trigger warning in debug mode."""
        from src.core.config import Settings, _validate_settings
        import warnings

        s = Settings(
            jwt_secret_key="change_this_to_a_random_secret_key_in_production",
            debug=True,
            gemini_api_key="test-key",
            postgres_password="test",
            neo4j_password="test",
        )
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            _validate_settings(s)
            security_warnings = [x for x in w if "SECURITY" in str(x.message)]
            assert len(security_warnings) > 0

    def test_weak_jwt_error_production(self):
        """Weak JWT secret should raise error in production (debug=False)."""
        from src.core.config import Settings, _validate_settings

        s = Settings(
            jwt_secret_key="change_this_to_a_random_secret_key_in_production",
            debug=False,
            gemini_api_key="test-key",
            postgres_password="test",
            neo4j_password="test",
        )
        with pytest.raises(ValueError, match="Critical configuration"):
            _validate_settings(s)

    def test_strong_config_passes(self):
        """Strong configuration should pass without errors."""
        from src.core.config import Settings, _validate_settings

        s = Settings(
            jwt_secret_key="a" * 48,  # Strong enough
            debug=False,
            gemini_api_key="valid-key",
            postgres_password="strong-pass",
            neo4j_password="strong-pass",
        )
        # Should not raise
        _validate_settings(s)
