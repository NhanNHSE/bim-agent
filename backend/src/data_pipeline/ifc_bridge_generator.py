"""IFC Bridge Generator — Concrete Beam Bridge (Cầu dầm BTCT).

Generates IFC4 files for Vietnamese highway bridges with:
- Piers (trụ cầu) with rectangular profile
- Abutments (mố cầu) at both ends
- Deck slabs (bản mặt cầu) per span
- Girders with I-profile (dầm cầu BTCT dự ứng lực)
- Barriers/Railings (lan can thép)
- Bearings (gối cầu cao su)
- Pile foundations (cọc khoan nhồi)

Compatible with: Autodesk Revit/Civil 3D, Bentley RM Bridge (via IFC4).
Foundation data exported as JSON for PLAXIS 3D input.

Standards: TCVN 11823:2017, 22TCN 272-05
"""

import json
import math
import os
from typing import Optional

import ifcopenshell
import ifcopenshell.api
import numpy as np
import structlog

from src.data_pipeline.base_spec import BridgeSpec

logger = structlog.get_logger()

run = ifcopenshell.api.run


def generate_bridge(spec: BridgeSpec, output_dir: str = "data/ifc") -> str:
    """Generate an IFC4 file for a concrete beam bridge.

    Args:
        spec: BridgeSpec with all bridge parameters.
        output_dir: Directory to save the IFC file.

    Returns:
        Filepath to the generated IFC file.

    Raises:
        RuntimeError: If IFC generation fails.
    """
    os.makedirs(output_dir, exist_ok=True)
    safe_name = spec.bridge_name.replace(" ", "_").replace("/", "_")
    filepath = os.path.join(output_dir, f"{safe_name}.ifc")

    try:
        model = run("project.create_file", version="IFC4")
        project = run("root.create_entity", model, ifc_class="IfcProject",
                      name=spec.project_name)
        run("unit.assign_unit", model, length={"is_metric": True, "raw": "MILLIMETERS"})

        ctx = run("context.add_context", model, context_type="Model")
        body = run("context.add_context", model, context_type="Model",
                   context_identifier="Body", target_view="MODEL_VIEW", parent=ctx)

        site = run("root.create_entity", model, ifc_class="IfcSite", name="Mặt bằng cầu")
        # IFC4 doesn't have IfcBridge, use IfcBuilding as container
        bridge = run("root.create_entity", model, ifc_class="IfcBuilding",
                     name=spec.bridge_name)
        run("aggregate.assign_object", model, relating_object=project, products=[site])
        run("aggregate.assign_object", model, relating_object=site, products=[bridge])

        # Create a single "storey" to contain all bridge elements
        # Bridge uses elevation 0 as deck level
        storey = run("root.create_entity", model, ifc_class="IfcBuildingStorey",
                     name="Kết cấu cầu")
        run("geometry.edit_object_placement", model, product=storey,
            matrix=_mat4(0, 0, 0))
        run("aggregate.assign_object", model, relating_object=bridge, products=[storey])

        # Create materials
        mats = _create_bridge_materials(model, spec)

        # ===== Generate bridge elements =====

        # 1. Abutments (mố cầu) at both ends
        _mk_abutment(model, body, storey, mats, spec, "Mố A1", x=0, is_start=True)
        _mk_abutment(model, body, storey, mats, spec, "Mố A2",
                     x=spec.total_length, is_start=False)

        # 2. Piers (trụ cầu) between spans
        for i in range(spec.num_piers):
            px = spec.span_length * (i + 1)
            _mk_pier(model, body, storey, mats, spec, f"Trụ T{i+1}", px)

        # 3. Girders (dầm cầu) — per span
        for span_idx in range(spec.num_spans):
            span_start = span_idx * spec.span_length
            _mk_girders(model, body, storey, mats, spec, span_idx, span_start)

        # 4. Deck slabs (bản mặt cầu) — per span
        for span_idx in range(spec.num_spans):
            span_start = span_idx * spec.span_length
            _mk_deck(model, body, storey, mats, spec,
                     f"Sàn cầu S{span_idx+1}", span_start)

        # 5. Barriers/Railings (lan can) — continuous along both sides
        _mk_barriers(model, body, storey, mats, spec)

        # 6. Bearings (gối cầu) — on each pier and abutment
        _mk_bearings(model, body, storey, mats, spec)

        # 7. Pile foundations (cọc móng)
        _mk_pile_foundations(model, body, storey, mats, spec)

        # Write IFC file
        model.write(filepath)
        logger.info("bridge_ifc_generated", filepath=filepath,
                    spans=spec.num_spans, bridge_type=spec.bridge_type,
                    schema="IFC4", total_length=spec.total_length)

    except Exception as e:
        logger.error("bridge_ifc_generation_failed", error=str(e),
                     bridge_name=spec.bridge_name)
        # Cleanup partial file
        if os.path.exists(filepath):
            os.remove(filepath)
        raise RuntimeError(
            f"Lỗi tạo IFC cầu '{spec.bridge_name}': {e}"
        ) from e

    # Export foundation JSON for PLAXIS 3D (non-critical)
    try:
        _export_foundation_json(spec, output_dir, safe_name)
    except Exception as e:
        logger.warning("foundation_json_export_failed", error=str(e))

    return filepath


# ===== Materials =====

def _create_bridge_materials(model, spec: BridgeSpec) -> dict:
    """Create all materials used in the bridge."""
    mats = {}
    material_names = {
        spec.deck_material, spec.girder_material, spec.pier_material,
        spec.abutment_material, spec.barrier_material, spec.pile_material,
        "Cao su tổng hợp",  # for bearings
    }
    for name in material_names:
        mats[name] = run("material.add_material", model, name=name)
    return mats


# ===== Element Builders =====

def _mk_pier(model, body, storey, mats, spec: BridgeSpec, name: str, x: float):
    """Create a pier (trụ cầu) at position x along bridge axis."""
    pier = run("root.create_entity", model, ifc_class="IfcColumn", name=name,
               predefined_type="PILASTER")

    profile = run("profile.add_parameterized_profile", model,
                  ifc_class="IfcRectangleProfileDef")
    profile.XDim = spec.pier_width
    profile.YDim = spec.pier_depth

    rep = run("geometry.add_profile_representation", model, context=body,
              profile=profile, depth=spec.pier_height)
    run("geometry.assign_representation", model, product=pier, representation=rep)

    # Pier center at x, centered on deck width, bottom at -pier_height
    pier_y = spec.deck_width / 2
    pier_z = -spec.pier_height
    run("geometry.edit_object_placement", model, product=pier,
        matrix=_mat4(x, pier_y, pier_z))
    run("spatial.assign_container", model, relating_structure=storey, products=[pier])
    run("material.assign_material", model, products=[pier],
        material=mats[spec.pier_material])

    pset = run("pset.add_pset", model, product=pier, name="Pset_ColumnCommon")
    run("pset.edit_pset", model, pset=pset, properties={
        "LoadBearing": True,
        "Reference": "PIER",
    })

    # Structural property set for RM Bridge compatibility
    pset2 = run("pset.add_pset", model, product=pier, name="Pset_BridgePier")
    run("pset.edit_pset", model, pset=pset2, properties={
        "PierHeight": spec.pier_height,
        "PierWidth": spec.pier_width,
        "PierDepth": spec.pier_depth,
        "ConcreteGrade": spec.pier_material,
    })
    return pier


def _mk_abutment(model, body, storey, mats, spec: BridgeSpec,
                  name: str, x: float, is_start: bool):
    """Create an abutment (mố cầu) at bridge end."""
    # Abutment wall
    abt = run("root.create_entity", model, ifc_class="IfcWall", name=name,
              predefined_type="STANDARD")

    rep = run("geometry.add_wall_representation", model, context=body,
              length=spec.abutment_width,
              height=spec.abutment_height,
              thickness=spec.abutment_depth)
    run("geometry.assign_representation", model, product=abt, representation=rep)

    # Position: start abutment at x=0 (offset back by depth), end at x=total_length
    ax = x - spec.abutment_depth if is_start else x
    az = -spec.abutment_height
    run("geometry.edit_object_placement", model, product=abt,
        matrix=_mat4(ax, 0, az))
    run("spatial.assign_container", model, relating_structure=storey, products=[abt])
    run("material.assign_material", model, products=[abt],
        material=mats[spec.abutment_material])

    pset = run("pset.add_pset", model, product=abt, name="Pset_WallCommon")
    run("pset.edit_pset", model, pset=pset, properties={
        "IsExternal": True,
        "LoadBearing": True,
        "Reference": "ABUTMENT_START" if is_start else "ABUTMENT_END",
    })

    # Footing under abutment
    footing = run("root.create_entity", model, ifc_class="IfcFooting",
                  name=f"Móng {name}", predefined_type="STRIP_FOOTING")
    f_width = spec.abutment_width + 1000  # 500mm overhang each side
    f_depth = spec.abutment_depth + 1000
    f_thickness = spec.pile_cap_thickness

    profile = run("profile.add_parameterized_profile", model,
                  ifc_class="IfcRectangleProfileDef")
    profile.XDim = f_depth
    profile.YDim = f_width

    rep = run("geometry.add_profile_representation", model, context=body,
              profile=profile, depth=f_thickness)
    run("geometry.assign_representation", model, product=footing, representation=rep)
    run("geometry.edit_object_placement", model, product=footing,
        matrix=_mat4(ax - 500, -500, -spec.abutment_height - f_thickness))
    run("spatial.assign_container", model, relating_structure=storey, products=[footing])
    run("material.assign_material", model, products=[footing],
        material=mats[spec.pier_material])

    return abt


def _mk_girders(model, body, storey, mats, spec: BridgeSpec,
                span_idx: int, span_start: float):
    """Create girders for one span using I-profile."""
    spacing = spec.deck_width / (spec.num_girders + 1)

    for gi in range(spec.num_girders):
        name = f"Dầm G{gi+1} N{span_idx+1}"
        girder = run("root.create_entity", model, ifc_class="IfcBeam", name=name,
                     predefined_type="BEAM")

        # I-profile for RM Bridge / Revit compatibility
        profile = run("profile.add_parameterized_profile", model,
                      ifc_class="IfcIShapeProfileDef")
        profile.OverallWidth = spec.girder_width
        profile.OverallDepth = spec.girder_height
        profile.WebThickness = spec.girder_web_thickness
        profile.FlangeThickness = spec.girder_flange_thickness

        rep = run("geometry.add_profile_representation", model, context=body,
                  profile=profile, depth=spec.span_length)
        run("geometry.assign_representation", model, product=girder,
            representation=rep)

        # Position: along x-axis, spaced across y
        gy = spacing * (gi + 1)
        gz = -spec.girder_height  # below deck level
        run("geometry.edit_object_placement", model, product=girder,
            matrix=_mat4(span_start, gy, gz))
        run("spatial.assign_container", model, relating_structure=storey,
            products=[girder])
        run("material.assign_material", model, products=[girder],
            material=mats[spec.girder_material])

        pset = run("pset.add_pset", model, product=girder, name="Pset_BeamCommon")
        run("pset.edit_pset", model, pset=pset, properties={
            "LoadBearing": True,
            "Span": spec.span_length,
            "Reference": f"GIRDER_SPAN{span_idx+1}",
        })


def _mk_deck(model, body, storey, mats, spec: BridgeSpec,
             name: str, span_start: float):
    """Create a deck slab for one span."""
    deck = run("root.create_entity", model, ifc_class="IfcSlab", name=name,
               predefined_type="FLOOR")

    polyline = [
        (0.0, 0.0),
        (spec.span_length, 0.0),
        (spec.span_length, spec.deck_width),
        (0.0, spec.deck_width),
        (0.0, 0.0),
    ]
    rep = run("geometry.add_slab_representation", model, context=body,
              depth=spec.deck_thickness, polyline=polyline)
    run("geometry.assign_representation", model, product=deck, representation=rep)
    run("geometry.edit_object_placement", model, product=deck,
        matrix=_mat4(span_start, 0, 0))
    run("spatial.assign_container", model, relating_structure=storey, products=[deck])
    run("material.assign_material", model, products=[deck],
        material=mats[spec.deck_material])

    pset = run("pset.add_pset", model, product=deck, name="Pset_SlabCommon")
    run("pset.edit_pset", model, pset=pset, properties={
        "IsExternal": True,
        "LoadBearing": True,
        "Reference": "BRIDGE_DECK",
    })
    return deck


def _mk_barriers(model, body, storey, mats, spec: BridgeSpec):
    """Create barrier railings on both sides of the bridge."""
    for side_idx, (side_name, y_pos) in enumerate([
        ("Lan can trái", 0.0),
        ("Lan can phải", spec.deck_width),
    ]):
        # Continuous barrier as a series of posts + rail
        num_posts = int(spec.total_length / spec.barrier_post_spacing) + 1

        for pi in range(num_posts):
            px = pi * spec.barrier_post_spacing
            if px > spec.total_length:
                px = spec.total_length

            post_name = f"{side_name} P{pi+1}"
            post = run("root.create_entity", model, ifc_class="IfcRailing",
                       name=post_name, predefined_type="GUARDRAIL")

            profile = run("profile.add_parameterized_profile", model,
                          ifc_class="IfcRectangleProfileDef")
            profile.XDim = 100  # post width
            profile.YDim = 100  # post depth

            rep = run("geometry.add_profile_representation", model, context=body,
                      profile=profile, depth=spec.barrier_height)
            run("geometry.assign_representation", model, product=post,
                representation=rep)
            run("geometry.edit_object_placement", model, product=post,
                matrix=_mat4(px, y_pos, spec.deck_thickness))
            run("spatial.assign_container", model, relating_structure=storey,
                products=[post])
            run("material.assign_material", model, products=[post],
                material=mats[spec.barrier_material])

        # Top rail (horizontal beam along the full length)
        rail_name = f"{side_name} Thanh ngang"
        rail = run("root.create_entity", model, ifc_class="IfcRailing",
                   name=rail_name, predefined_type="GUARDRAIL")

        profile = run("profile.add_parameterized_profile", model,
                      ifc_class="IfcRectangleProfileDef")
        profile.XDim = 80
        profile.YDim = 80

        rep = run("geometry.add_profile_representation", model, context=body,
                  profile=profile, depth=spec.total_length)
        run("geometry.assign_representation", model, product=rail,
            representation=rep)
        rail_z = spec.deck_thickness + spec.barrier_height - 80
        run("geometry.edit_object_placement", model, product=rail,
            matrix=_mat4(0, y_pos, rail_z))
        run("spatial.assign_container", model, relating_structure=storey,
            products=[rail])
        run("material.assign_material", model, products=[rail],
            material=mats[spec.barrier_material])


def _mk_bearings(model, body, storey, mats, spec: BridgeSpec):
    """Create bearings on top of each pier and abutment."""
    # Bearing positions: on each pier + 2 abutments
    bearing_x_positions = [0.0]  # abutment A1
    for i in range(spec.num_piers):
        bearing_x_positions.append(spec.span_length * (i + 1))
    bearing_x_positions.append(spec.total_length)  # abutment A2

    for bi, bx in enumerate(bearing_x_positions):
        # Place num_girders bearings at each support
        spacing = spec.deck_width / (spec.num_girders + 1)
        for gi in range(spec.num_girders):
            name = f"Gối G{gi+1} V{bi+1}"
            bearing = run("root.create_entity", model,
                          ifc_class="IfcBuildingElementProxy", name=name,
                          predefined_type="PROVISIONFORSPACE")

            profile = run("profile.add_parameterized_profile", model,
                          ifc_class="IfcRectangleProfileDef")
            profile.XDim = spec.bearing_length
            profile.YDim = spec.bearing_width

            rep = run("geometry.add_profile_representation", model, context=body,
                      profile=profile, depth=spec.bearing_height)
            run("geometry.assign_representation", model, product=bearing,
                representation=rep)

            by = spacing * (gi + 1)
            bz = -spec.girder_height - spec.bearing_height
            run("geometry.edit_object_placement", model, product=bearing,
                matrix=_mat4(bx - spec.bearing_length / 2, by, bz))
            run("spatial.assign_container", model, relating_structure=storey,
                products=[bearing])
            run("material.assign_material", model, products=[bearing],
                material=mats["Cao su tổng hợp"])


def _mk_pile_foundations(model, body, storey, mats, spec: BridgeSpec):
    """Create pile foundations under each pier."""
    # Piles under each pier
    for pi in range(spec.num_piers):
        px = spec.span_length * (pi + 1)
        _mk_pile_group(model, body, storey, mats, spec,
                       f"Trụ T{pi+1}", px, spec.pier_height)

    # Piles under abutments
    _mk_pile_group(model, body, storey, mats, spec,
                   "Mố A1", 0, spec.abutment_height)
    _mk_pile_group(model, body, storey, mats, spec,
                   "Mố A2", spec.total_length, spec.abutment_height)


def _mk_pile_group(model, body, storey, mats, spec: BridgeSpec,
                   parent_name: str, x: float, support_height: float):
    """Create a group of piles under a pier or abutment."""
    n = spec.num_piles_per_pier
    # Arrange in a grid (2×2 for 4 piles, 2×3 for 6, etc.)
    cols = min(n, 2)
    rows = math.ceil(n / cols)

    pile_spacing_x = spec.pier_width * 2
    pile_spacing_y = spec.pier_depth * 2

    cap_z = -support_height - spec.pile_cap_thickness

    pile_idx = 0
    for row in range(rows):
        for col in range(cols):
            if pile_idx >= n:
                break
            pile_idx += 1

            name = f"Cọc {parent_name} C{pile_idx}"
            pile = run("root.create_entity", model, ifc_class="IfcPile",
                       name=name, predefined_type="BORED")

            # Circular profile for bored pile
            profile = run("profile.add_parameterized_profile", model,
                          ifc_class="IfcCircleProfileDef")
            profile.Radius = spec.pile_diameter / 2

            rep = run("geometry.add_profile_representation", model, context=body,
                      profile=profile, depth=spec.pile_depth)
            run("geometry.assign_representation", model, product=pile,
                representation=rep)

            # Position below pile cap
            cx = x + (col - (cols - 1) / 2) * pile_spacing_x
            cy = spec.deck_width / 2 + (row - (rows - 1) / 2) * pile_spacing_y
            cz = cap_z - spec.pile_depth
            run("geometry.edit_object_placement", model, product=pile,
                matrix=_mat4(cx, cy, cz))
            run("spatial.assign_container", model, relating_structure=storey,
                products=[pile])
            run("material.assign_material", model, products=[pile],
                material=mats[spec.pile_material])

            pset = run("pset.add_pset", model, product=pile,
                       name="Pset_PileCommon")
            run("pset.edit_pset", model, pset=pset, properties={
                "LoadBearing": True,
                "DesignParameters": f"D={spec.pile_diameter}mm, L={spec.pile_depth}mm",
            })


# ===== Foundation Export for PLAXIS 3D =====

def _export_foundation_json(spec: BridgeSpec, output_dir: str, safe_name: str):
    """Export foundation parameters as JSON for PLAXIS 3D input."""
    data = {
        "project": spec.project_name,
        "bridge": spec.bridge_name,
        "foundation_type": spec.foundation_type,
        "design_standard": "TCVN 11823:2017",
        "supports": [],
    }

    # Abutments
    for i, name in enumerate(["Mố A1", "Mố A2"]):
        x = 0 if i == 0 else spec.total_length
        data["supports"].append({
            "name": name,
            "type": "abutment",
            "x_position_mm": x,
            "pile_cap": {
                "width_mm": spec.abutment_width + 1000,
                "depth_mm": spec.abutment_depth + 1000,
                "thickness_mm": spec.pile_cap_thickness,
            },
            "piles": {
                "count": spec.num_piles_per_pier,
                "diameter_mm": spec.pile_diameter,
                "depth_mm": spec.pile_depth,
                "type": "bored",
                "material": spec.pile_material,
            },
        })

    # Piers
    for i in range(spec.num_piers):
        px = spec.span_length * (i + 1)
        data["supports"].append({
            "name": f"Trụ T{i+1}",
            "type": "pier",
            "x_position_mm": px,
            "pier": {
                "height_mm": spec.pier_height,
                "width_mm": spec.pier_width,
                "depth_mm": spec.pier_depth,
                "material": spec.pier_material,
            },
            "pile_cap": {
                "width_mm": spec.pier_depth * 3,
                "depth_mm": spec.pier_width * 3,
                "thickness_mm": spec.pile_cap_thickness,
            },
            "piles": {
                "count": spec.num_piles_per_pier,
                "diameter_mm": spec.pile_diameter,
                "depth_mm": spec.pile_depth,
                "type": "bored",
                "material": spec.pile_material,
            },
        })

    filepath = os.path.join(output_dir, f"{safe_name}_foundation.json")
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logger.info("foundation_json_exported", filepath=filepath)
    return filepath


# ===== Helpers =====

def _mat4(x, y, z):
    """4×4 translation matrix."""
    return np.array([
        [1, 0, 0, x],
        [0, 1, 0, y],
        [0, 0, 1, z],
        [0, 0, 0, 1],
    ], dtype=float)
