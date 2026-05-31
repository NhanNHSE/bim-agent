"""Build knowledge graph from parsed QCVN/TCVN data into Neo4j."""

import json
import os
from typing import Any

import structlog

from src.knowledge_graph.neo4j_client import run_write_query
from src.knowledge_graph.graph_schema import init_schema

logger = structlog.get_logger()


def build_graph_from_json(filepath: str) -> dict[str, int]:
    """Build knowledge graph nodes and relationships from a structured JSON file.

    Args:
        filepath: Path to the QCVN/TCVN JSON file.

    Returns:
        Summary of nodes and relationships created.
    """
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    counters = {"nodes": 0, "relationships": 0}

    # 1. Create Standard node
    _create_standard_node(data, counters)

    # 2. Create chapters, sections, articles
    for chapter in data.get("chapters", []):
        _create_chapter(data["standard_code"], chapter, counters)

    # 3. Create cross-references between standards
    _create_standard_references(data, counters)

    logger.info(
        "graph_built",
        standard=data["standard_code"],
        nodes=counters["nodes"],
        relationships=counters["relationships"],
    )
    return counters


def _create_standard_node(data: dict, counters: dict):
    """Create a Standard node."""
    run_write_query(
        """
        MERGE (s:Standard {code: $code})
        SET s.name = $name,
            s.year = $year,
            s.issuing_body = $issuing_body,
            s.status = $status,
            s.scope = $scope
        """,
        {
            "code": data["standard_code"],
            "name": data["standard_name"],
            "year": data.get("year", 0),
            "issuing_body": data.get("issuing_body", ""),
            "status": data.get("status", "active"),
            "scope": data.get("scope", ""),
        },
    )
    counters["nodes"] += 1


def _create_chapter(standard_code: str, chapter: dict, counters: dict):
    """Create Chapter node and link to Standard."""
    chapter_id = f"{standard_code}_ch{chapter['number']}"

    run_write_query(
        """
        MATCH (s:Standard {code: $standard_code})
        MERGE (ch:Chapter {chapter_id: $chapter_id})
        SET ch.number = $number, ch.title = $title
        MERGE (s)-[:CONTAINS]->(ch)
        """,
        {
            "standard_code": standard_code,
            "chapter_id": chapter_id,
            "number": chapter["number"],
            "title": chapter["title"],
        },
    )
    counters["nodes"] += 1
    counters["relationships"] += 1

    for section in chapter.get("sections", []):
        _create_section(standard_code, chapter_id, section, counters)


def _create_section(
    standard_code: str, chapter_id: str, section: dict, counters: dict
):
    """Create Section node and link to Chapter."""
    section_id = f"{standard_code}_sec{section['number']}"

    run_write_query(
        """
        MATCH (ch:Chapter {chapter_id: $chapter_id})
        MERGE (sec:Section {section_id: $section_id})
        SET sec.number = $number, sec.title = $title
        MERGE (ch)-[:HAS_SECTION]->(sec)
        """,
        {
            "chapter_id": chapter_id,
            "section_id": section_id,
            "number": section["number"],
            "title": section["title"],
        },
    )
    counters["nodes"] += 1
    counters["relationships"] += 1

    for article in section.get("articles", []):
        _create_article(standard_code, section_id, article, counters)


def _create_article(
    standard_code: str, section_id: str, article: dict, counters: dict
):
    """Create Article node with requirements and link to Section."""
    article_id = f"{standard_code}_art{article['number']}"

    run_write_query(
        """
        MATCH (sec:Section {section_id: $section_id})
        MERGE (a:Article {article_id: $article_id})
        SET a.number = $number,
            a.title = $title,
            a.content = $content,
            a.standard_code = $standard_code
        MERGE (sec)-[:HAS_ARTICLE]->(a)
        """,
        {
            "section_id": section_id,
            "article_id": article_id,
            "number": article["number"],
            "title": article["title"],
            "content": article["content"],
            "standard_code": standard_code,
        },
    )
    counters["nodes"] += 1
    counters["relationships"] += 1

    # Create Requirement nodes
    for i, req in enumerate(article.get("requirements", [])):
        _create_requirement(article_id, i, req, counters)


def _create_requirement(
    article_id: str, index: int, req: dict, counters: dict
):
    """Create Requirement node and link to Article."""
    req_id = f"{article_id}_req{index}"
    req_json = json.dumps(req.get("values", {}), ensure_ascii=False)

    run_write_query(
        """
        MATCH (a:Article {article_id: $article_id})
        MERGE (r:Requirement {req_id: $req_id})
        SET r.type = $type,
            r.description = $description,
            r.values_json = $values_json,
            r.applies_to = $applies_to,
            r.condition = $condition
        MERGE (a)-[:SPECIFIES]->(r)
        """,
        {
            "article_id": article_id,
            "req_id": req_id,
            "type": req.get("type", ""),
            "description": req.get("description", ""),
            "values_json": req_json,
            "applies_to": req.get("applies_to", ""),
            "condition": req.get("condition", ""),
        },
    )
    counters["nodes"] += 1
    counters["relationships"] += 1

    # Create BuildingType/Material nodes from classification values
    _create_domain_nodes(req, req_id, counters)


def _create_domain_nodes(req: dict, req_id: str, counters: dict):
    """Create domain-specific nodes (BuildingType, Material) from requirements."""
    if req.get("type") == "classification" and "applies_to" not in req:
        # Building type classifications (e.g., F1, F2, ...)
        for code, description in req.get("values", {}).items():
            if isinstance(description, str):
                run_write_query(
                    """
                    MERGE (bt:BuildingType {code: $code})
                    SET bt.description = $description
                    WITH bt
                    MATCH (r:Requirement {req_id: $req_id})
                    MERGE (r)-[:CLASSIFIES]->(bt)
                    """,
                    {"code": code, "description": description, "req_id": req_id},
                )
                counters["nodes"] += 1
                counters["relationships"] += 1

    elif req.get("type") == "material_property":
        for material_name, props in req.get("values", {}).items():
            if isinstance(props, dict):
                run_write_query(
                    """
                    MERGE (m:Material {name: $name})
                    SET m.unit_weight = $value, m.unit = $unit
                    WITH m
                    MATCH (r:Requirement {req_id: $req_id})
                    MERGE (r)-[:FOR_MATERIAL]->(m)
                    """,
                    {
                        "name": material_name,
                        "value": props.get("value", 0),
                        "unit": props.get("unit", ""),
                        "req_id": req_id,
                    },
                )
                counters["nodes"] += 1
                counters["relationships"] += 1


def _create_standard_references(data: dict, counters: dict):
    """Create RELATED_TO and SUPERSEDES relationships between standards."""
    standard_code = data["standard_code"]

    # Supersedes
    if data.get("supersedes"):
        run_write_query(
            """
            MATCH (s:Standard {code: $code})
            MERGE (old:Standard {code: $supersedes})
            ON CREATE SET old.status = 'superseded'
            MERGE (s)-[:SUPERSEDES]->(old)
            """,
            {"code": standard_code, "supersedes": data["supersedes"]},
        )
        counters["relationships"] += 1

    # Related standards
    for related_code in data.get("related_standards", []):
        run_write_query(
            """
            MATCH (s:Standard {code: $code})
            MERGE (r:Standard {code: $related_code})
            MERGE (s)-[:RELATED_TO]->(r)
            """,
            {"code": standard_code, "related_code": related_code},
        )
        counters["relationships"] += 1


def build_graph_from_directory(data_dir: str = "data/qcvn") -> dict[str, int]:
    """Build knowledge graph from all JSON files in a directory.

    Args:
        data_dir: Directory containing QCVN/TCVN JSON files.

    Returns:
        Total summary of nodes and relationships created.
    """
    init_schema()

    total = {"nodes": 0, "relationships": 0}

    if not os.path.exists(data_dir):
        logger.warning("data_directory_not_found", path=data_dir)
        return total

    json_files = [f for f in os.listdir(data_dir) if f.endswith(".json")]
    logger.info("building_graph", files_found=len(json_files), directory=data_dir)

    for filename in json_files:
        filepath = os.path.join(data_dir, filename)
        try:
            counters = build_graph_from_json(filepath)
            total["nodes"] += counters["nodes"]
            total["relationships"] += counters["relationships"]
        except Exception as e:
            logger.error("graph_build_failed", file=filename, error=str(e))

    logger.info("graph_build_complete", total_nodes=total["nodes"],
                total_relationships=total["relationships"])
    return total
