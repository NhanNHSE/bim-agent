"""IFC Parser — Extract structured BIM data from IFC files.

Uses ifcopenshell to parse IFC 2x3/4 files and extract:
- Building hierarchy: Site → Building → Storey → Space
- Elements: Wall, Column, Beam, Slab, Door, Window
- Materials and property sets
- Spatial relationships
- Geometry (simplified mesh for 3D viewer)
"""

import json
import os
from dataclasses import dataclass, field, asdict
from typing import Optional

import structlog

logger = structlog.get_logger()


@dataclass
class BIMElement:
    """Represents a single BIM element."""
    global_id: str
    ifc_type: str
    name: str
    storey: str = ""
    material: str = ""
    properties: dict = field(default_factory=dict)
    geometry: Optional[dict] = None  # {vertices: [], faces: []}


@dataclass
class BIMStorey:
    """A building storey."""
    name: str
    elevation: float = 0.0
    elements: list = field(default_factory=list)


@dataclass
class BIMSpace:
    """A room/space within a storey."""
    global_id: str
    name: str
    long_name: str = ""
    storey: str = ""
    area: float = 0.0
    bounded_by: list = field(default_factory=list)


@dataclass
class ParsedIFC:
    """Complete parsed IFC data."""
    filename: str
    schema: str = ""
    project_name: str = ""
    site_name: str = ""
    building_name: str = ""
    storeys: list = field(default_factory=list)
    elements: list = field(default_factory=list)
    spaces: list = field(default_factory=list)
    materials: list = field(default_factory=list)
    element_count: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)


# ===== Element type mapping =====
ELEMENT_TYPES = {
    "IfcWall": "Tường",
    "IfcWallStandardCase": "Tường",
    "IfcColumn": "Cột",
    "IfcBeam": "Dầm",
    "IfcSlab": "Sàn",
    "IfcDoor": "Cửa đi",
    "IfcWindow": "Cửa sổ",
    "IfcStair": "Cầu thang",
    "IfcRailing": "Lan can",
    "IfcRoof": "Mái",
    "IfcCovering": "Lớp phủ",
    "IfcCurtainWall": "Tường rèm",
    "IfcPlate": "Bản thép",
    "IfcMember": "Thanh",
    "IfcFooting": "Móng",
    "IfcPile": "Cọc",
}


def parse_ifc(filepath: str, extract_geometry: bool = False) -> ParsedIFC:
    """Parse an IFC file and extract structured BIM data.

    Args:
        filepath: Path to .ifc file.
        extract_geometry: If True, extract simplified mesh geometry.

    Returns:
        ParsedIFC with all extracted data.
    """
    try:
        import ifcopenshell
        import ifcopenshell.util.element as ifc_util
    except ImportError:
        logger.error("ifcopenshell_not_installed")
        raise ImportError("ifcopenshell is required. Install with: pip install ifcopenshell")

    logger.info("parsing_ifc", filepath=filepath)

    ifc_file = ifcopenshell.open(filepath)
    result = ParsedIFC(filename=os.path.basename(filepath))

    # Schema
    result.schema = ifc_file.schema

    # Project
    projects = ifc_file.by_type("IfcProject")
    if projects:
        result.project_name = projects[0].Name or "Unnamed Project"

    # Site
    sites = ifc_file.by_type("IfcSite")
    if sites:
        result.site_name = sites[0].Name or "Unnamed Site"

    # Building
    buildings = ifc_file.by_type("IfcBuilding")
    if buildings:
        result.building_name = buildings[0].Name or "Unnamed Building"

    # Storeys
    storeys = ifc_file.by_type("IfcBuildingStorey")
    storey_map = {}
    for storey in storeys:
        elevation = 0.0
        if storey.Elevation is not None:
            elevation = float(storey.Elevation)
        bim_storey = BIMStorey(
            name=storey.Name or f"Storey_{storey.id()}",
            elevation=elevation,
        )
        result.storeys.append(asdict(bim_storey))
        storey_map[storey.id()] = bim_storey.name
    logger.info("storeys_found", count=len(result.storeys))

    # Elements
    element_count = {}
    for ifc_type in ELEMENT_TYPES:
        elements = ifc_file.by_type(ifc_type)
        if elements:
            element_count[ifc_type] = len(elements)

        for el in elements:
            # Get storey
            storey_name = _get_storey_name(el, storey_map)

            # Get material
            material = _get_material(el)

            # Get properties
            props = _get_properties(el)

            bim_el = BIMElement(
                global_id=el.GlobalId or "",
                ifc_type=ifc_type,
                name=el.Name or f"{ifc_type}_{el.id()}",
                storey=storey_name,
                material=material,
                properties=props,
            )

            # Geometry (simplified)
            if extract_geometry:
                bim_el.geometry = _extract_geometry(el, ifc_file)

            result.elements.append(asdict(bim_el))

    result.element_count = element_count
    logger.info("elements_parsed", count=len(result.elements), types=element_count)

    # Spaces
    spaces = ifc_file.by_type("IfcSpace")
    for space in spaces:
        storey_name = _get_storey_name(space, storey_map)
        area = 0.0
        # Try to get area from quantity sets
        for rel in getattr(space, "IsDefinedBy", []):
            if hasattr(rel, "RelatingPropertyDefinition"):
                pdef = rel.RelatingPropertyDefinition
                if hasattr(pdef, "Quantities"):
                    for q in pdef.Quantities:
                        if hasattr(q, "AreaValue") and q.AreaValue:
                            area = float(q.AreaValue)

        bim_space = BIMSpace(
            global_id=space.GlobalId or "",
            name=space.Name or f"Space_{space.id()}",
            long_name=space.LongName or "",
            storey=storey_name,
            area=area,
        )
        result.spaces.append(asdict(bim_space))
    logger.info("spaces_found", count=len(result.spaces))

    # Materials (unique list)
    mat_set = set()
    for el in result.elements:
        if el.get("material"):
            mat_set.add(el["material"])
    result.materials = sorted(mat_set)
    logger.info("materials_found", count=len(result.materials))

    return result


def _get_storey_name(element, storey_map: dict) -> str:
    """Get the storey name for an element via spatial containment."""
    for rel in getattr(element, "ContainedInStructure", []):
        if hasattr(rel, "RelatingStructure"):
            structure = rel.RelatingStructure
            if structure.id() in storey_map:
                return storey_map[structure.id()]
            # Check parent
            if hasattr(structure, "Decomposes"):
                for decomp in structure.Decomposes:
                    parent = decomp.RelatingObject
                    if parent.id() in storey_map:
                        return storey_map[parent.id()]
    return ""


def _get_material(element) -> str:
    """Extract primary material name from an element."""
    for rel in getattr(element, "HasAssociations", []):
        if rel.is_a("IfcRelAssociatesMaterial"):
            mat = rel.RelatingMaterial
            if mat.is_a("IfcMaterial"):
                return mat.Name or ""
            elif mat.is_a("IfcMaterialLayerSetUsage") or mat.is_a("IfcMaterialLayerSet"):
                layer_set = mat if mat.is_a("IfcMaterialLayerSet") else mat.ForLayerSet
                if layer_set and hasattr(layer_set, "MaterialLayers"):
                    names = []
                    for layer in layer_set.MaterialLayers:
                        if layer.Material and layer.Material.Name:
                            names.append(layer.Material.Name)
                    return " + ".join(names) if names else ""
            elif mat.is_a("IfcMaterialList"):
                names = [m.Name for m in mat.Materials if m.Name]
                return " + ".join(names) if names else ""
    return ""


def _get_properties(element) -> dict:
    """Extract key properties from property sets."""
    props = {}
    for rel in getattr(element, "IsDefinedBy", []):
        if hasattr(rel, "RelatingPropertyDefinition"):
            pdef = rel.RelatingPropertyDefinition
            if hasattr(pdef, "HasProperties"):
                for prop in pdef.HasProperties:
                    if hasattr(prop, "NominalValue") and prop.NominalValue:
                        val = prop.NominalValue.wrappedValue
                        if val is not None:
                            props[prop.Name] = val
    # Keep only interesting properties (limit size)
    interesting = [
        "Width", "Height", "Length", "Thickness", "Area", "Volume",
        "FireRating", "IsExternal", "LoadBearing", "Reference",
    ]
    filtered = {}
    for key in interesting:
        if key in props:
            filtered[key] = props[key]
    return filtered


def _extract_geometry(element, ifc_file) -> Optional[dict]:
    """Extract simplified geometry (bounding box) for 3D preview."""
    try:
        import ifcopenshell.geom
        settings = ifcopenshell.geom.settings()
        settings.set(settings.USE_WORLD_COORDS, True)
        shape = ifcopenshell.geom.create_shape(settings, element)
        verts = shape.geometry.verts
        faces = shape.geometry.faces

        # Convert flat arrays to grouped
        vertices = [[verts[i], verts[i+1], verts[i+2]] for i in range(0, len(verts), 3)]
        indices = [[faces[i], faces[i+1], faces[i+2]] for i in range(0, len(faces), 3)]

        return {"vertices": vertices, "faces": indices}
    except Exception:
        return None


def get_ifc_summary(parsed: ParsedIFC) -> str:
    """Generate a text summary of parsed IFC data for embedding."""
    lines = [
        f"Dự án: {parsed.project_name}",
        f"Công trình: {parsed.building_name}",
        f"Schema: {parsed.schema}",
        f"Số tầng: {len(parsed.storeys)}",
    ]

    for storey in parsed.storeys:
        lines.append(f"  - {storey['name']} (cao độ {storey['elevation']}m)")

    lines.append(f"\nTổng số cấu kiện: {sum(parsed.element_count.values())}")
    for ifc_type, count in parsed.element_count.items():
        vn_name = ELEMENT_TYPES.get(ifc_type, ifc_type)
        lines.append(f"  - {vn_name} ({ifc_type}): {count}")

    if parsed.materials:
        lines.append(f"\nVật liệu sử dụng ({len(parsed.materials)}):")
        for mat in parsed.materials:
            lines.append(f"  - {mat}")

    if parsed.spaces:
        lines.append(f"\nKhông gian ({len(parsed.spaces)}):")
        for space in parsed.spaces:
            area_str = f" — {space['area']:.1f}m²" if space.get("area") else ""
            lines.append(f"  - {space['name']}{area_str} [{space['storey']}]")

    return "\n".join(lines)
