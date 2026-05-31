"""Knowledge Graph schema and constraints for Neo4j.

Defines node labels, relationship types, and indexes for the QCVN/TCVN
knowledge graph. Also includes IFC-ready schema for Phase 2.
"""

from src.knowledge_graph.neo4j_client import run_write_query
import structlog

logger = structlog.get_logger()

# ===== Schema Definition =====

# Phase 1: QCVN/TCVN Standards
SCHEMA_CONSTRAINTS = [
    # Unique constraints
    "CREATE CONSTRAINT standard_code IF NOT EXISTS FOR (s:Standard) REQUIRE s.code IS UNIQUE",
    "CREATE CONSTRAINT article_id IF NOT EXISTS FOR (a:Article) REQUIRE a.article_id IS UNIQUE",
    "CREATE CONSTRAINT concept_name IF NOT EXISTS FOR (c:Concept) REQUIRE c.name IS UNIQUE",
    "CREATE CONSTRAINT material_name IF NOT EXISTS FOR (m:Material) REQUIRE m.name IS UNIQUE",
    "CREATE CONSTRAINT building_type_code IF NOT EXISTS FOR (b:BuildingType) REQUIRE b.code IS UNIQUE",
]

SCHEMA_INDEXES = [
    # Full-text indexes for search
    "CREATE FULLTEXT INDEX article_content IF NOT EXISTS FOR (a:Article) ON EACH [a.content, a.title]",
    # Regular indexes
    "CREATE INDEX standard_year IF NOT EXISTS FOR (s:Standard) ON (s.year)",
    "CREATE INDEX standard_status IF NOT EXISTS FOR (s:Standard) ON (s.status)",
    "CREATE INDEX article_number IF NOT EXISTS FOR (a:Article) ON (a.number)",
    "CREATE INDEX requirement_type IF NOT EXISTS FOR (r:Requirement) ON (r.type)",
]


def init_schema():
    """Initialize the knowledge graph schema in Neo4j.

    Creates constraints and indexes. Safe to run multiple times (IF NOT EXISTS).
    """
    logger.info("initializing_graph_schema")

    for constraint in SCHEMA_CONSTRAINTS:
        try:
            run_write_query(constraint)
        except Exception as e:
            logger.warning("constraint_creation_warning", query=constraint, error=str(e))

    for index in SCHEMA_INDEXES:
        try:
            run_write_query(index)
        except Exception as e:
            logger.warning("index_creation_warning", query=index, error=str(e))

    logger.info("graph_schema_initialized",
                constraints=len(SCHEMA_CONSTRAINTS),
                indexes=len(SCHEMA_INDEXES))


def clear_graph():
    """Delete all nodes and relationships. Use with caution!"""
    logger.warning("clearing_entire_graph")
    run_write_query("MATCH (n) DETACH DELETE n")
    logger.info("graph_cleared")
