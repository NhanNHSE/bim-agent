"""IFC to Knowledge Graph — Import parsed IFC data into Neo4j.

Creates graph structure:
  (Building) -[:HAS_STOREY]-> (Storey)   Storey is keyed by storey_id = "<building>::<name>",
                                         so "Tầng 1" of different buildings stay separate
  (Storey) -[:CONTAINS]-> (Element)
  (Element) -[:MADE_OF]-> (Material)
  (Storey) -[:CONTAINS]-> (Space)
  (Element) -- various spatial relationships
"""

import structlog
from neo4j import GraphDatabase

from src.core.config import get_settings

logger = structlog.get_logger()
settings = get_settings()


def build_ifc_graph(parsed_ifc: dict) -> dict:
    """Import parsed IFC data into Neo4j knowledge graph.

    Args:
        parsed_ifc: Dict from ParsedIFC.to_dict()

    Returns:
        Stats dict with counts of created nodes/relationships.
    """
    driver = GraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password),
    )

    stats = {"nodes": 0, "relationships": 0}

    with driver.session() as session:
        # Create constraints (idempotent)
        _create_constraints(session)

        # Create Building node
        building_name = parsed_ifc.get("building_name", "Unknown")
        project_name = parsed_ifc.get("project_name", "Unknown")
        session.run(
            """
            MERGE (b:Building {name: $name})
            SET b.project = $project, b.schema = $schema, b.filename = $filename
            """,
            name=building_name,
            project=project_name,
            schema=parsed_ifc.get("schema", ""),
            filename=parsed_ifc.get("filename", ""),
        )
        stats["nodes"] += 1
        logger.info("building_created", name=building_name)

        # Create Storeys
        for storey in parsed_ifc.get("storeys", []):
            session.run(
                """
                MERGE (s:Storey {storey_id: $storey_id})
                SET s.name = $name, s.building = $building, s.elevation = $elevation
                WITH s
                MATCH (b:Building {name: $building})
                MERGE (b)-[:HAS_STOREY]->(s)
                """,
                storey_id=_storey_id(building_name, storey["name"]),
                name=storey["name"],
                elevation=storey.get("elevation", 0),
                building=building_name,
            )
            stats["nodes"] += 1
            stats["relationships"] += 1

        # Create Materials
        for material in parsed_ifc.get("materials", []):
            session.run(
                "MERGE (m:Material {name: $name})",
                name=material,
            )
            stats["nodes"] += 1

        # Create Elements
        for el in parsed_ifc.get("elements", []):
            ifc_type = el.get("ifc_type", "Unknown")
            label = _ifc_type_to_label(ifc_type)

            session.run(
                f"""
                MERGE (e:{label} {{global_id: $global_id}})
                SET e.name = $name, e.ifc_type = $ifc_type,
                    e.storey = $storey, e.material = $material,
                    e.properties = $properties_json
                """,
                global_id=el.get("global_id", ""),
                name=el.get("name", ""),
                ifc_type=ifc_type,
                storey=el.get("storey", ""),
                material=el.get("material", ""),
                properties_json=str(el.get("properties", {})),
            )
            stats["nodes"] += 1

            # Storey → Element relationship
            if el.get("storey"):
                session.run(
                    f"""
                    MATCH (s:Storey {{storey_id: $storey_id}})
                    MATCH (e:{label} {{global_id: $global_id}})
                    MERGE (s)-[:CONTAINS]->(e)
                    """,
                    storey_id=_storey_id(building_name, el["storey"]),
                    global_id=el["global_id"],
                )
                stats["relationships"] += 1

            # Element → Material relationship
            if el.get("material"):
                session.run(
                    f"""
                    MATCH (e:{label} {{global_id: $global_id}})
                    MATCH (m:Material {{name: $material}})
                    MERGE (e)-[:MADE_OF]->(m)
                    """,
                    global_id=el["global_id"],
                    material=el["material"],
                )
                stats["relationships"] += 1

        # Create Spaces
        for space in parsed_ifc.get("spaces", []):
            session.run(
                """
                MERGE (sp:Space {global_id: $global_id})
                SET sp.name = $name, sp.long_name = $long_name,
                    sp.storey = $storey, sp.area = $area
                """,
                global_id=space.get("global_id", ""),
                name=space.get("name", ""),
                long_name=space.get("long_name", ""),
                storey=space.get("storey", ""),
                area=space.get("area", 0),
            )
            stats["nodes"] += 1

            if space.get("storey"):
                session.run(
                    """
                    MATCH (s:Storey {storey_id: $storey_id})
                    MATCH (sp:Space {global_id: $global_id})
                    MERGE (s)-[:CONTAINS]->(sp)
                    """,
                    storey_id=_storey_id(building_name, space["storey"]),
                    global_id=space["global_id"],
                )
                stats["relationships"] += 1

    driver.close()
    logger.info("ifc_graph_built", **stats)
    return stats


def get_ifc_building_summary() -> dict:
    """Get summary statistics of imported IFC data from Neo4j."""
    driver = GraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password),
    )

    with driver.session() as session:
        result = session.run("""
            MATCH (b:Building)
            OPTIONAL MATCH (b)-[:HAS_STOREY]->(s:Storey)
            WITH b, collect(DISTINCT s.name) AS storeys
            RETURN b.name AS building, b.project AS project,
                   b.filename AS filename, storeys
        """).single()

        building = dict(result) if result else {}

        # Element counts by type
        counts_result = session.run("""
            MATCH (e)
            WHERE e:Wall OR e:Column OR e:Beam OR e:Slab OR e:Door OR e:Window
            RETURN labels(e)[0] AS type, count(e) AS count
            ORDER BY count DESC
        """)
        element_counts = {r["type"]: r["count"] for r in counts_result}

        # Materials
        mat_result = session.run("MATCH (m:Material) RETURN m.name AS name")
        materials = [r["name"] for r in mat_result]

        # Spaces
        space_result = session.run("""
            MATCH (sp:Space)
            RETURN sp.name AS name, sp.storey AS storey, sp.area AS area
            ORDER BY sp.storey, sp.name
        """)
        spaces = [dict(r) for r in space_result]

    driver.close()

    return {
        **building,
        "element_counts": element_counts,
        "materials": materials,
        "spaces": spaces,
        "total_elements": sum(element_counts.values()),
    }


def query_elements_on_storey(storey_name: str) -> list:
    """Get all elements on a specific storey."""
    driver = GraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password),
    )
    with driver.session() as session:
        result = session.run("""
            MATCH (s:Storey {name: $storey})-[:CONTAINS]->(e)
            RETURN labels(e)[0] AS type, e.name AS name,
                   e.material AS material, e.properties AS properties
            ORDER BY type, name
        """, storey=storey_name)
        elements = [dict(r) for r in result]
    driver.close()
    return elements


def query_material_usage(material_name: str) -> list:
    """Get all elements using a specific material."""
    driver = GraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password),
    )
    with driver.session() as session:
        result = session.run("""
            MATCH (e)-[:MADE_OF]->(m:Material)
            WHERE m.name CONTAINS $material
            RETURN labels(e)[0] AS type, e.name AS name,
                   e.storey AS storey, m.name AS material
            ORDER BY e.storey, type
        """, material=material_name)
        elements = [dict(r) for r in result]
    driver.close()
    return elements


def _storey_id(building: str, storey: str) -> str:
    return f"{building}::{storey}"


def _create_constraints(session):
    """Create uniqueness constraints; migrate the old global `Storey.name` uniqueness."""
    # Databases created before storey_id had UNIQUE(Storey.name): drop it and key old storeys
    for record in session.run(
        "SHOW CONSTRAINTS YIELD name, labelsOrTypes, properties "
        "WHERE labelsOrTypes = ['Storey'] AND properties = ['name'] RETURN name"
    ):
        # constraint names come from the database itself, not from user input
        session.run(f"DROP CONSTRAINT `{record['name']}` IF EXISTS")
    session.run(
        """
        MATCH (b:Building)-[:HAS_STOREY]->(s:Storey)
        WHERE s.storey_id IS NULL
        WITH s, min(b.name) AS building
        SET s.storey_id = building + '::' + s.name, s.building = building
        """
    )
    constraints = [
        "CREATE CONSTRAINT IF NOT EXISTS FOR (b:Building) REQUIRE b.name IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (s:Storey) REQUIRE s.storey_id IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (m:Material) REQUIRE m.name IS UNIQUE",
    ]
    for c in constraints:
        try:
            session.run(c)
        except Exception as e:
            logger.warning("ifc_constraint_failed", query=c, error=str(e))


def _ifc_type_to_label(ifc_type: str) -> str:
    """Map IFC type to Neo4j node label."""
    mapping = {
        "IfcWall": "Wall",
        "IfcWallStandardCase": "Wall",
        "IfcColumn": "Column",
        "IfcBeam": "Beam",
        "IfcSlab": "Slab",
        "IfcDoor": "Door",
        "IfcWindow": "Window",
        "IfcStair": "Stair",
        "IfcRailing": "Railing",
        "IfcRoof": "Roof",
        "IfcFooting": "Footing",
        "IfcPile": "Pile",
        "IfcCurtainWall": "CurtainWall",
        "IfcSpace": "Space",
    }
    return mapping.get(ifc_type, "BIMElement")
