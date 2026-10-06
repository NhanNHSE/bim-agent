"""Tests for Graph Query Generator — Cypher safety validation."""

import pytest


from src.knowledge_graph.graph_query_generator import _validate_cypher


class TestCypherValidation:
    """Test that dangerous Cypher queries are blocked."""

    def test_safe_match_query(self):
        is_safe, reason = _validate_cypher(
            "MATCH (s:Standard) RETURN s.code, s.name LIMIT 10"
        )
        assert is_safe is True

    def test_safe_multi_match(self):
        is_safe, reason = _validate_cypher(
            "MATCH (a:Article)-[:SPECIFIES]->(r:Requirement) "
            "MATCH (r)-[:CLASSIFIES]->(bt:BuildingType) "
            "RETURN a.title, bt.code LIMIT 20"
        )
        assert is_safe is True

    def test_safe_optional_match(self):
        is_safe, reason = _validate_cypher(
            "OPTIONAL MATCH (s:Standard)-[:CONTAINS]->(c:Chapter) "
            "RETURN s.code, c.title LIMIT 10"
        )
        assert is_safe is True

    def test_safe_with_clause(self):
        is_safe, reason = _validate_cypher(
            "WITH 'F1' AS code "
            "MATCH (bt:BuildingType {code: code}) "
            "RETURN bt.description LIMIT 5"
        )
        assert is_safe is True

    # === Dangerous queries that MUST be blocked ===

    def test_block_delete(self):
        is_safe, reason = _validate_cypher(
            "MATCH (n) DELETE n"
        )
        assert is_safe is False
        assert "DELETE" in reason

    def test_block_detach_delete(self):
        is_safe, reason = _validate_cypher(
            "MATCH (n) DETACH DELETE n"
        )
        assert is_safe is False

    def test_block_create(self):
        is_safe, reason = _validate_cypher(
            "CREATE (n:Hacker {name: 'evil'})"
        )
        assert is_safe is False

    def test_block_merge(self):
        is_safe, reason = _validate_cypher(
            "MERGE (n:Standard {code: 'FAKE'})"
        )
        assert is_safe is False

    def test_block_set(self):
        is_safe, reason = _validate_cypher(
            "MATCH (s:Standard) SET s.code = 'HACKED' RETURN s"
        )
        assert is_safe is False

    def test_block_remove(self):
        is_safe, reason = _validate_cypher(
            "MATCH (n) REMOVE n.code RETURN n"
        )
        assert is_safe is False

    def test_block_drop(self):
        is_safe, reason = _validate_cypher(
            "DROP INDEX article_content"
        )
        assert is_safe is False

    def test_block_load_csv(self):
        is_safe, reason = _validate_cypher(
            "LOAD CSV FROM 'http://evil.com/data.csv' AS row "
            "CREATE (n:Data {val: row[0]}) RETURN n"
        )
        assert is_safe is False

    def test_block_no_return(self):
        is_safe, reason = _validate_cypher(
            "MATCH (n:Standard) WITH n LIMIT 10"
        )
        assert is_safe is False
        assert "RETURN" in reason

    def test_block_starts_with_call_apoc(self):
        is_safe, reason = _validate_cypher(
            "CALL apoc.export.csv.all('data.csv', {})"
        )
        assert is_safe is False
