"""Build knowledge graph from parsed QCVN/TCVN data into Neo4j.

Graph: (Standard)-[:CONTAINS]->(Chapter)-[:HAS_SECTION]->(Section)-[:HAS_ARTICLE]->(Article)
       -[:SPECIFIES]->(Requirement), plus SUPERSEDES / RELATED_TO between standards and
       BuildingType / Material nodes for classification and material requirements.

Each standard is rebuilt as a whole: its previous chapters/sections/articles/requirements are
deleted first, so a re-ingest never leaves stale clauses behind. Writes are batched with
UNWIND (one query per level instead of one per node).
"""

import json
import os
from pathlib import Path

import structlog

from src.knowledge_graph.neo4j_client import run_write_query
from src.knowledge_graph.graph_schema import init_schema

logger = structlog.get_logger()

BATCH_SIZE = 500


def _batches(rows: list[dict]):
    for start in range(0, len(rows), BATCH_SIZE):
        yield rows[start:start + BATCH_SIZE]


def _rows(data: dict) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    """Flatten a standard into chapter / section / article / requirement rows."""
    code = data["standard_code"]
    chapters, sections, articles, requirements = [], [], [], []
    for chapter in data.get("chapters", []):
        chapter_id = f"{code}_ch{chapter['number']}"
        chapters.append({
            "chapter_id": chapter_id, "number": str(chapter["number"]),
            "title": chapter.get("title", ""), "kind": chapter.get("kind", "chapter"),
        })
        for section in chapter.get("sections", []):
            section_id = f"{code}_sec{section['number']}"
            sections.append({
                "chapter_id": chapter_id, "section_id": section_id,
                "number": str(section["number"]), "title": section.get("title", ""),
            })
            for article in section.get("articles", []):
                article_id = f"{code}_art{article['number']}"
                articles.append({
                    "section_id": section_id, "article_id": article_id,
                    "number": str(article["number"]), "title": article.get("title", ""),
                    "content": article.get("content", ""),
                })
                for i, req in enumerate(article.get("requirements", [])):
                    requirements.append({
                        "article_id": article_id, "req_id": f"{article_id}_req{i}", "req": req,
                        "type": req.get("type", ""), "description": req.get("description", ""),
                        "values_json": json.dumps(req.get("values", {}), ensure_ascii=False),
                        "min_value": req.get("min_value"), "max_value": req.get("max_value"),
                        "unit": req.get("unit", ""),
                        "applies_to": req.get("applies_to", ""), "condition": req.get("condition", ""),
                    })
    return chapters, sections, articles, requirements


def build_graph_from_dict(data: dict) -> dict[str, int]:
    """Rebuild one standard's subgraph from its structured dict."""
    code = data["standard_code"]
    counters = {"nodes": 0, "relationships": 0}

    _create_standard_node(data, counters)
    _delete_standard_content(code)

    chapters, sections, articles, requirements = _rows(data)
    for batch in _batches(chapters):
        run_write_query(
            """
            MATCH (s:Standard {code: $code})
            UNWIND $rows AS row
            MERGE (ch:Chapter {chapter_id: row.chapter_id})
            SET ch.number = row.number, ch.title = row.title, ch.kind = row.kind
            MERGE (s)-[:CONTAINS]->(ch)
            """,
            {"code": code, "rows": batch},
        )
    for batch in _batches(sections):
        run_write_query(
            """
            UNWIND $rows AS row
            MATCH (ch:Chapter {chapter_id: row.chapter_id})
            MERGE (sec:Section {section_id: row.section_id})
            SET sec.number = row.number, sec.title = row.title
            MERGE (ch)-[:HAS_SECTION]->(sec)
            """,
            {"rows": batch},
        )
    for batch in _batches(articles):
        run_write_query(
            """
            UNWIND $rows AS row
            MATCH (sec:Section {section_id: row.section_id})
            MERGE (a:Article {article_id: row.article_id})
            SET a.number = row.number, a.title = row.title, a.content = row.content,
                a.standard_code = $code
            MERGE (sec)-[:HAS_ARTICLE]->(a)
            """,
            {"code": code, "rows": batch},
        )
    for batch in _batches(requirements):
        run_write_query(
            """
            UNWIND $rows AS row
            MATCH (a:Article {article_id: row.article_id})
            MERGE (r:Requirement {req_id: row.req_id})
            SET r.type = row.type, r.description = row.description, r.values_json = row.values_json,
                r.min_value = row.min_value, r.max_value = row.max_value, r.unit = row.unit,
                r.applies_to = row.applies_to, r.condition = row.condition
            MERGE (a)-[:SPECIFIES]->(r)
            """,
            {"rows": [{k: v for k, v in row.items() if k != "req"} for row in batch]},
        )
    for row in requirements:
        _create_domain_nodes(row["req"], row["req_id"], counters)

    counters["nodes"] += len(chapters) + len(sections) + len(articles) + len(requirements)
    counters["relationships"] += len(chapters) + len(sections) + len(articles) + len(requirements)
    _create_standard_references(data, counters)

    logger.info("graph_built", standard=code, nodes=counters["nodes"], relationships=counters["relationships"])
    return counters


def build_graph_from_json(filepath: str) -> dict[str, int]:
    """Build knowledge graph nodes and relationships from a structured JSON file.

    Args:
        filepath: Path to the QCVN/TCVN JSON file.

    Returns:
        Summary of nodes and relationships created.
    """
    with open(filepath, "r", encoding="utf-8") as f:
        return build_graph_from_dict(json.load(f))


def _create_standard_node(data: dict, counters: dict):
    """Create or update the Standard node, including its validity."""
    run_write_query(
        """
        MERGE (s:Standard {code: $code})
        SET s.name = $name,
            s.year = $year,
            s.issuing_body = $issuing_body,
            s.status = $status,
            s.eff_status = $eff_status,
            s.expired = $expired,
            s.effective_date = $effective_date,
            s.doc_num = $doc_num,
            s.vbpl_url = $vbpl_url,
            s.full_text = $full_text,
            s.scope = $scope
        """,
        {
            "code": data["standard_code"],
            "name": data["standard_name"],
            "year": data.get("year", 0),
            "issuing_body": data.get("issuing_body", ""),
            "status": data.get("status", "active"),
            "eff_status": data.get("eff_status", ""),
            "expired": bool(data.get("expired", False)),
            "effective_date": data.get("effective_date", ""),
            "doc_num": data.get("doc_num", ""),
            "vbpl_url": data.get("vbpl_url", ""),
            "full_text": data.get("full_text", True),
            "scope": data.get("scope", ""),
        },
    )
    counters["nodes"] += 1


def _delete_standard_content(code: str):
    """Remove the previous chapters/sections/articles/requirements of a standard."""
    run_write_query(
        """
        MATCH (s:Standard {code: $code})-[:CONTAINS]->(ch:Chapter)
        OPTIONAL MATCH (ch)-[:HAS_SECTION]->(sec:Section)
        OPTIONAL MATCH (sec)-[:HAS_ARTICLE]->(a:Article)
        OPTIONAL MATCH (a)-[:SPECIFIES]->(r:Requirement)
        DETACH DELETE r, a, sec, ch
        """,
        {"code": code},
    )


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

    # Supersedes: a placeholder node created here is marked superseded; a real node keeps
    # the status from its own data (vbpl validity is authoritative)
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

    related = [c for c in data.get("related_standards", []) if c != standard_code]
    if related:
        run_write_query(
            """
            MATCH (s:Standard {code: $code})
            UNWIND $related AS related_code
            MERGE (r:Standard {code: related_code})
            MERGE (s)-[:RELATED_TO]->(r)
            """,
            {"code": standard_code, "related": related},
        )
        counters["relationships"] += len(related)


def build_graph_from_directory(data_dir: str = "data/vbpl_bxd/parsed") -> dict[str, int]:
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

    json_files = sorted(f for f in os.listdir(data_dir) if f.endswith(".json") and not f.startswith("_"))
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


def prune_standards(keep: set[str]) -> None:
    """Delete regulations (with their content) built earlier but absent from this corpus."""
    if not keep:
        raise ValueError("refusing to prune with an empty keep set")
    run_write_query(
        """
        MATCH (s:Standard)-[:CONTAINS]->(:Chapter)
        WHERE NOT s.code IN $keep
        WITH DISTINCT s
        OPTIONAL MATCH (s)-[:CONTAINS]->(ch:Chapter)
        OPTIONAL MATCH (ch)-[:HAS_SECTION]->(sec:Section)
        OPTIONAL MATCH (sec)-[:HAS_ARTICLE]->(a:Article)
        OPTIONAL MATCH (a)-[:SPECIFIES]->(r:Requirement)
        DETACH DELETE r, a, sec, ch, s
        """,
        {"keep": sorted(keep)},
    )


def build_graph_for_corpus(json_dir: Path, prune: bool = True) -> dict[str, int]:
    """Build knowledge graph from directory and optionally prune standards not in corpus.

    Args:
        json_dir: Directory containing parsed standard JSON files.
        prune: Whether to remove standards not in this corpus.

    Returns:
        Summary dict with 'nodes' and 'relationships' counts.

    Raises:
        ValueError: If no standard JSON files are found, or if any JSON file is invalid or missing standard_code.
    """
    json_dir = Path(json_dir)
    files = sorted(f for f in os.listdir(json_dir) if f.endswith(".json") and not f.startswith("_")) if json_dir.exists() else []
    if not files:
        raise ValueError(f"No standard JSON files in {json_dir}")

    keep: set[str] = set()
    for f in files:
        filepath = json_dir / f
        try:
            data = json.loads(filepath.read_text(encoding="utf-8"))
        except Exception as e:
            raise ValueError(f"Invalid JSON file {f}: {e}") from e
        code = data.get("standard_code")
        if not code:
            raise ValueError(f"Missing standard_code in {f}")
        keep.add(code)

    result = build_graph_from_directory(str(json_dir))
    if prune:
        prune_standards(keep)
    return result

