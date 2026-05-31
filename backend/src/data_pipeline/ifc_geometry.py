"""Extract 3D geometry from IFC files for frontend rendering.

Parses an IFC file using ifcopenshell.geom and returns mesh data
(vertices, faces, colors, metadata) that the frontend can render
directly with Three.js. This ensures the 3D viewer shows exactly
what's in the IFC file.
"""

import os
import hashlib
import json
from typing import Optional

import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.util.element
import numpy as np
import structlog

logger = structlog.get_logger()

# Bump when mesh output format changes to invalidate caches
CACHE_VERSION = 2

# IFC type → color (RGB 0-1)
TYPE_COLORS = {
    # Building elements
    "IfcWall":      (0.91, 0.88, 0.83),
    "IfcColumn":    (0.69, 0.69, 0.69),
    "IfcBeam":      (0.63, 0.63, 0.63),
    "IfcSlab":      (0.78, 0.75, 0.71),
    "IfcDoor":      (0.43, 0.30, 0.25),
    "IfcWindow":    (0.50, 0.85, 1.00),
    "IfcStair":     (0.74, 0.67, 0.64),
    "IfcRailing":   (0.38, 0.49, 0.55),
    "IfcFooting":   (0.55, 0.43, 0.39),
    "IfcRoof":      (0.47, 0.56, 0.61),
    "IfcCovering":  (0.85, 0.82, 0.78),
    "IfcSpace":     (0.60, 0.80, 0.60),
    # Bridge elements
    "IfcPile":                  (0.50, 0.40, 0.30),  # Dark brown
    "IfcCivilElement":          (0.60, 0.60, 0.65),  # Bridge grey
    "IfcBuildingElementProxy":  (0.35, 0.65, 0.65),  # Teal (bearings)
}

# Default color for unknown types
DEFAULT_COLOR = (0.7, 0.7, 0.7)

# Opacity overrides
TYPE_OPACITY = {
    "IfcWindow": 0.3,
    "IfcSpace": 0.15,
    "IfcCovering": 0.6,
}


def extract_geometry(filepath: str, cache_dir: Optional[str] = None) -> dict:
    """Extract all geometry from an IFC file.
    
    Returns dict with:
        - meshes: list of {vertices, faces, color, opacity, meta}
        - stats: element counts, bounding box, etc.
    """
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"IFC file not found: {filepath}")

    # Check cache
    if cache_dir:
        cache_key = _file_hash(filepath)
        cache_path = os.path.join(cache_dir, f"{cache_key}_v{CACHE_VERSION}.json")
        if os.path.exists(cache_path):
            logger.info("geometry_cache_hit", filepath=filepath)
            with open(cache_path, "r") as f:
                return json.load(f)

    model = ifcopenshell.open(filepath)
    settings = ifcopenshell.geom.settings()
    settings.set(settings.USE_WORLD_COORDS, True)

    meshes = []
    element_counts = {}
    bbox_min = [float('inf')] * 3
    bbox_max = [float('-inf')] * 3

    products = model.by_type("IfcProduct")
    logger.info("geometry_extraction_start", filepath=filepath, products=len(products))

    for product in products:
        if not product.Representation:
            continue

        ifc_type = product.is_a()

        # Skip spaces and openings (not visible geometry)
        if ifc_type in ("IfcSpace", "IfcOpeningElement"):
            continue

        try:
            shape = ifcopenshell.geom.create_shape(settings, product)
        except Exception:
            continue

        geo = shape.geometry
        verts = list(geo.verts)   # flat [x1,y1,z1, x2,y2,z2, ...]
        faces = list(geo.faces)   # flat [i1,i2,i3, ...]

        if len(verts) < 9 or len(faces) < 3:
            continue

        # Update bounding box (vectorized with numpy)
        verts_arr = np.array(verts).reshape(-1, 3)
        bbox_min = np.minimum(bbox_min, verts_arr.min(axis=0)).tolist()
        bbox_max = np.maximum(bbox_max, verts_arr.max(axis=0)).tolist()

        # Color & opacity
        color = list(TYPE_COLORS.get(ifc_type, DEFAULT_COLOR))
        opacity = TYPE_OPACITY.get(ifc_type, 1.0)

        # Try to get material color from IFC
        try:
            if geo.materials and len(geo.materials) > 0:
                mat = geo.materials[0]
                if hasattr(mat, 'diffuse') and mat.diffuse:
                    color = [mat.diffuse[0], mat.diffuse[1], mat.diffuse[2]]
                if hasattr(mat, 'transparency') and mat.transparency:
                    opacity = 1.0 - mat.transparency
        except Exception:
            pass

        # Extract metadata
        meta = {
            "id": product.GlobalId,
            "type": ifc_type.replace("Ifc", ""),
            "name": product.Name or ifc_type,
        }

        # Get storey
        try:
            container = ifcopenshell.util.element.get_container(product)
            if container:
                meta["storey"] = container.Name
        except Exception:
            pass

        # Get material name
        try:
            mat_sets = ifcopenshell.util.element.get_material(product)
            if mat_sets:
                if hasattr(mat_sets, 'Name'):
                    meta["material"] = mat_sets.Name
                elif hasattr(mat_sets, 'ForLayerSet'):
                    meta["material"] = mat_sets.ForLayerSet.LayerSetName
        except Exception:
            pass

        # Get psets
        try:
            psets = ifcopenshell.util.element.get_psets(product)
            props = {}
            for pset_name, pset_props in psets.items():
                if pset_name.startswith("Pset_"):
                    for k, v in pset_props.items():
                        if k != "id" and v is not None:
                            props[k] = str(v)
            if props:
                meta["properties"] = props
        except Exception:
            pass

        # Count elements
        element_counts[meta["type"]] = element_counts.get(meta["type"], 0) + 1

        meshes.append({
            "v": [round(v, 4) for v in verts],
            "f": faces,
            "c": [round(c, 3) for c in color],
            "o": round(opacity, 2),
            "m": meta,
        })

    # Stats
    storeys = model.by_type("IfcBuildingStorey")
    building = model.by_type("IfcBuilding")

    result = {
        "meshes": meshes,
        "stats": {
            "element_counts": element_counts,
            "total_elements": sum(element_counts.values()),
            "storeys": [s.Name for s in storeys],
            "building_name": building[0].Name if building else "Unknown",
            "schema": model.schema,
            "bbox_min": [round(v, 2) for v in bbox_min],
            "bbox_max": [round(v, 2) for v in bbox_max],
        }
    }

    # Save to cache
    if cache_dir:
        os.makedirs(cache_dir, exist_ok=True)
        with open(cache_path, "w") as f:
            json.dump(result, f)
        logger.info("geometry_cached", cache_path=cache_path)

    logger.info("geometry_extraction_done",
                meshes=len(meshes), elements=result["stats"]["total_elements"])
    return result


def _file_hash(filepath: str) -> str:
    """Quick hash based on file path + size + mtime."""
    stat = os.stat(filepath)
    key = f"{filepath}:{stat.st_size}:{stat.st_mtime}"
    return hashlib.md5(key.encode()).hexdigest()
