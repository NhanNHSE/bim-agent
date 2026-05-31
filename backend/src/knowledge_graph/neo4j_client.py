"""Neo4j client with connection pooling and health check."""

from contextlib import contextmanager
from typing import Any, Optional

from neo4j import GraphDatabase, Driver
import structlog

from src.core.config import get_settings

logger = structlog.get_logger()
settings = get_settings()

_driver: Optional[Driver] = None


def get_driver() -> Driver:
    """Get or create the Neo4j driver (singleton)."""
    global _driver
    if _driver is None:
        _driver = GraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
            max_connection_pool_size=50,
        )
        logger.info("neo4j_connected", uri=settings.neo4j_uri)
    return _driver


def close_driver():
    """Close the Neo4j driver."""
    global _driver
    if _driver is not None:
        _driver.close()
        _driver = None
        logger.info("neo4j_disconnected")


def health_check() -> bool:
    """Check if Neo4j is reachable."""
    try:
        driver = get_driver()
        with driver.session() as session:
            session.run("RETURN 1")
        return True
    except Exception as e:
        logger.error("neo4j_health_check_failed", error=str(e))
        return False


def run_query(
    query: str,
    parameters: Optional[dict] = None,
    database: str = "neo4j",
) -> list[dict[str, Any]]:
    """Execute a Cypher query and return results as list of dicts.

    Args:
        query: Cypher query string.
        parameters: Query parameters.
        database: Neo4j database name.

    Returns:
        List of result records as dictionaries.
    """
    driver = get_driver()
    with driver.session(database=database) as session:
        result = session.run(query, parameters or {})
        return [record.data() for record in result]


def run_write_query(
    query: str,
    parameters: Optional[dict] = None,
    database: str = "neo4j",
) -> dict[str, Any]:
    """Execute a write Cypher query within a transaction.

    Args:
        query: Cypher query string.
        parameters: Query parameters.
        database: Neo4j database name.

    Returns:
        Summary counters from the query execution.
    """
    driver = get_driver()
    with driver.session(database=database) as session:
        result = session.run(query, parameters or {})
        summary = result.consume()
        return {
            "nodes_created": summary.counters.nodes_created,
            "relationships_created": summary.counters.relationships_created,
            "properties_set": summary.counters.properties_set,
        }
