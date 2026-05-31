"""Cypher query templates for knowledge graph traversal.

Provides pre-built queries for common AEC lookup patterns:
- Single-hop: direct attribute lookup
- Multi-hop: traverse relationships to find connected info
- Cross-reference: find related standards
"""

from typing import Any
from src.knowledge_graph.neo4j_client import run_query
import structlog

logger = structlog.get_logger()


def search_articles_by_keyword(keyword: str, limit: int = 10) -> list[dict]:
    """Full-text search on article content.

    Args:
        keyword: Search term (Vietnamese).
        limit: Max results.

    Returns:
        Matching articles with context.
    """
    results = run_query(
        """
        CALL db.index.fulltext.queryNodes('article_content', $keyword)
        YIELD node, score
        WITH node AS a, score
        MATCH (s:Standard)-[:CONTAINS]->(:Chapter)-[:HAS_SECTION]->(:Section)-[:HAS_ARTICLE]->(a)
        RETURN a.article_id AS article_id,
               a.number AS article_number,
               a.title AS article_title,
               a.content AS content,
               s.code AS standard_code,
               s.name AS standard_name,
               score
        ORDER BY score DESC
        LIMIT $limit
        """,
        {"keyword": keyword, "limit": limit},
    )
    return results


def get_requirements_for_building_type(building_type_code: str) -> list[dict]:
    """Find all requirements that apply to a specific building type.

    Multi-hop: BuildingType ← Requirement ← Article ← Section ← Chapter ← Standard

    Args:
        building_type_code: e.g., "F1", "F2"

    Returns:
        List of requirements with full context.
    """
    results = run_query(
        """
        MATCH (bt:BuildingType {code: $code})<-[:CLASSIFIES]-(req:Requirement)<-[:SPECIFIES]-(a:Article)
        MATCH (s:Standard)-[:CONTAINS]->(:Chapter)-[:HAS_SECTION]->(:Section)-[:HAS_ARTICLE]->(a)
        RETURN a.article_id AS article_id,
               a.number AS article_number,
               a.title AS article_title,
               a.content AS content,
               req.description AS requirement,
               req.type AS req_type,
               req.values_json AS values,
               s.code AS standard_code,
               bt.description AS building_type
        """,
        {"code": building_type_code},
    )
    return results


def get_requirements_for_topic(topic: str, standard_code: str = None) -> list[dict]:
    """Find requirements related to a topic within a standard.

    Args:
        topic: Topic keyword (e.g., "thoát nạn", "chịu lửa").
        standard_code: Optional filter by standard.

    Returns:
        List of requirements.
    """
    if standard_code:
        results = run_query(
            """
            MATCH (s:Standard {code: $standard_code})-[:CONTAINS]->(ch:Chapter)
                  -[:HAS_SECTION]->(sec:Section)-[:HAS_ARTICLE]->(a:Article)
            WHERE a.content CONTAINS $topic OR a.title CONTAINS $topic
                  OR sec.title CONTAINS $topic OR ch.title CONTAINS $topic
            OPTIONAL MATCH (a)-[:SPECIFIES]->(req:Requirement)
            RETURN a.article_id AS article_id,
                   a.number AS article_number,
                   a.title AS article_title,
                   a.content AS content,
                   req.description AS requirement,
                   req.values_json AS values,
                   s.code AS standard_code,
                   ch.title AS chapter_title,
                   sec.title AS section_title
            """,
            {"standard_code": standard_code, "topic": topic},
        )
    else:
        results = run_query(
            """
            MATCH (s:Standard)-[:CONTAINS]->(ch:Chapter)
                  -[:HAS_SECTION]->(sec:Section)-[:HAS_ARTICLE]->(a:Article)
            WHERE a.content CONTAINS $topic OR a.title CONTAINS $topic
                  OR sec.title CONTAINS $topic OR ch.title CONTAINS $topic
            OPTIONAL MATCH (a)-[:SPECIFIES]->(req:Requirement)
            RETURN a.article_id AS article_id,
                   a.number AS article_number,
                   a.title AS article_title,
                   a.content AS content,
                   req.description AS requirement,
                   req.values_json AS values,
                   s.code AS standard_code,
                   ch.title AS chapter_title,
                   sec.title AS section_title
            """,
            {"topic": topic},
        )
    return results


def get_related_standards(standard_code: str) -> list[dict]:
    """Find all standards related to a given standard.

    Args:
        standard_code: e.g., "QCVN 06:2022/BXD"

    Returns:
        List of related standards with relationship type.
    """
    results = run_query(
        """
        MATCH (s:Standard {code: $code})
        OPTIONAL MATCH (s)-[r1:RELATED_TO]->(related:Standard)
        OPTIONAL MATCH (s)-[r2:SUPERSEDES]->(superseded:Standard)
        WITH s,
             collect(DISTINCT {code: related.code, name: related.name, rel: 'RELATED_TO'}) AS related_list,
             collect(DISTINCT {code: superseded.code, name: superseded.name, rel: 'SUPERSEDES'}) AS superseded_list
        RETURN s.code AS code, s.name AS name,
               related_list + superseded_list AS connections
        """,
        {"code": standard_code},
    )
    return results


def get_material_properties(material_name: str) -> list[dict]:
    """Find properties of a specific material.

    Args:
        material_name: e.g., "Bê tông cốt thép"

    Returns:
        Material properties from standards.
    """
    results = run_query(
        """
        MATCH (m:Material)
        WHERE m.name CONTAINS $name
        OPTIONAL MATCH (req:Requirement)-[:FOR_MATERIAL]->(m)
        OPTIONAL MATCH (a:Article)-[:SPECIFIES]->(req)
        OPTIONAL MATCH (s:Standard)-[:CONTAINS]->(:Chapter)-[:HAS_SECTION]->(:Section)-[:HAS_ARTICLE]->(a)
        RETURN m.name AS material,
               m.unit_weight AS unit_weight,
               m.unit AS unit,
               req.description AS requirement_description,
               a.title AS article_title,
               s.code AS standard_code
        """,
        {"name": material_name},
    )
    return results


def get_graph_stats() -> dict:
    """Get overall graph statistics."""
    results = run_query(
        """
        MATCH (n)
        WITH labels(n) AS label_list, count(n) AS cnt
        UNWIND label_list AS label
        RETURN label, sum(cnt) AS count
        ORDER BY count DESC
        """
    )
    stats = {r["label"]: r["count"] for r in results}

    rel_results = run_query(
        """
        MATCH ()-[r]->()
        RETURN type(r) AS rel_type, count(r) AS count
        ORDER BY count DESC
        """
    )
    stats["_relationships"] = {r["rel_type"]: r["count"] for r in rel_results}

    return stats
