"""IFC Generator v2 — Using IfcOpenShell High-Level API.

Generates IFC4 files with:
- Multi-layer walls (plaster + brick + plaster)
- Proper door/window with lining + panels
- Column profiles (rectangle)
- Beam profiles (rectangle)
- Material layer sets
- Property sets (Pset_WallCommon, etc.)
- Slab with polyline footprint
"""

import os
import math
from dataclasses import dataclass, field
from typing import Optional

from src.data_pipeline.base_spec import BaseSpec

import ifcopenshell
import ifcopenshell.api
import numpy as np
import structlog

logger = structlog.get_logger()

run = ifcopenshell.api.run


@dataclass
class BuildingSpec(BaseSpec):
    """Full building specification extracted from user description."""
    structure_type: str = "building"
    building_name: str = "Tòa nhà"
    building_type: str = "F2"  # F1=nhà ở, F2=công cộng
    building_function: str = "Văn phòng"

    num_storeys: int = 3
    storey_height: float = 3500.0
    footprint_length: float = 12000.0
    footprint_width: float = 8000.0

    wall_thickness: float = 200.0
    column_size: float = 400.0
    slab_thickness: float = 200.0
    beam_height: float = 400.0
    beam_width: float = 200.0

    wall_material: str = "Gạch ống 200mm"
    column_material: str = "Bê tông cốt thép B25"
    slab_material: str = "Bê tông cốt thép B25"
    beam_material: str = "Bê tông cốt thép B25"
    window_material: str = "Kính cường lực 10mm"

    num_interior_walls_x: int = 1
    num_interior_walls_y: int = 0
    doors_per_storey: int = 2
    windows_per_storey: int = 3
    num_staircases: int = 1

    column_spacing_x: float = 6000.0
    column_spacing_y: float = 8000.0

    spaces: list = field(default_factory=list)
    corridor_width: float = 1800.0
    has_lobby: bool = True
    has_toilet: bool = True
    has_foundation: bool = True
    footing_depth: float = 500.0
    has_roof_railing: bool = True
    railing_height: float = 1100.0
    riser_height: float = 170.0
    tread_depth: float = 300.0
    window_sill_height: float = 900.0


def generate_from_spec(spec: BuildingSpec, output_dir: str = "data/ifc") -> str:
    """Generate an IFC4 file from a BuildingSpec."""
    os.makedirs(output_dir, exist_ok=True)
    safe_name = spec.building_name.replace(" ", "_").replace("/", "_")
    filepath = os.path.join(output_dir, f"{safe_name}.ifc")

    model = run("project.create_file", version="IFC4")
    project = run("root.create_entity", model, ifc_class="IfcProject", name=spec.project_name)
    run("unit.assign_unit", model, length={"is_metric": True, "raw": "MILLIMETERS"})

    ctx = run("context.add_context", model, context_type="Model")
    body = run("context.add_context", model, context_type="Model",
               context_identifier="Body", target_view="MODEL_VIEW", parent=ctx)

    site = run("root.create_entity", model, ifc_class="IfcSite", name="Khu đất")
    building = run("root.create_entity", model, ifc_class="IfcBuilding", name=spec.building_name)
    run("aggregate.assign_object", model, relating_object=project, products=[site])
    run("aggregate.assign_object", model, relating_object=site, products=[building])

    mats = _create_materials(model, spec)
    col_grid = _auto_column_grid(spec)

    storeys = []
    for s in range(spec.num_storeys):
        elev = s * spec.storey_height
        storey = run("root.create_entity", model, ifc_class="IfcBuildingStorey",
                     name=f"Tầng {s + 1}")
        run("geometry.edit_object_placement", model, product=storey,
            matrix=_mat4(0, 0, elev))
        storeys.append(storey)
    run("aggregate.assign_object", model, relating_object=building, products=storeys)

    L, W = spec.footprint_length, spec.footprint_width
    wt = spec.wall_thickness
    cs = spec.column_size
    st = spec.slab_thickness

    # Determine which columns are interior (not on wall edges)
    interior_cols = []
    for cx, cy in col_grid:
        on_edge = (cx < wt + 1 or cx > L - wt - 1 or
                   cy < wt + 1 or cy > W - wt - 1)
        interior_cols.append(not on_edge)

    for s_idx, storey in enumerate(storeys):
        wall_h = spec.storey_height - st  # Wall height = storey - slab
        wall_z = st  # Walls start above slab

        # --- Slab (at bottom of storey, z=0) ---
        _mk_slab(model, body, storey, mats, spec, f"Sàn T{s_idx+1}",
                 L, W, st)

        # --- Exterior Walls (above slab, corners don't overlap) ---
        # North & South walls: full length
        _mk_wall(model, body, storey, mats, spec, f"Tường Bắc T{s_idx+1}",
                 0, 0, L, wall_h, wt, True, wall_z)
        _mk_wall(model, body, storey, mats, spec, f"Tường Nam T{s_idx+1}",
                 0, W - wt, L, wall_h, wt, True, wall_z)
        # East & West walls: shortened to avoid corner overlap
        _mk_wall(model, body, storey, mats, spec, f"Tường Tây T{s_idx+1}",
                 0, wt, wt, wall_h, W - 2 * wt, True, wall_z)
        _mk_wall(model, body, storey, mats, spec, f"Tường Đông T{s_idx+1}",
                 L - wt, wt, wt, wall_h, W - 2 * wt, True, wall_z)

        # --- Columns (only interior, not on wall lines) ---
        for ci, (cx, cy) in enumerate(col_grid):
            if interior_cols[ci]:
                _mk_column(model, body, storey, mats, spec,
                           f"Cột C{ci+1} T{s_idx+1}", cx, cy, spec.storey_height)

        # --- Beams (between column faces, at top under slab) ---
        _mk_beams(model, body, storey, mats, spec, col_grid, s_idx)

        # --- Doors on north wall (z starts above slab) ---
        for di in range(spec.doors_per_storey):
            dx = L / (spec.doors_per_storey + 1) * (di + 1)
            _mk_door(model, body, storey, spec, f"Cửa D{di+1} T{s_idx+1}",
                     dx - 450, 0, 900, 2100, wall_z)

        # --- Windows on south wall (sill_height is relative to floor) ---
        for wi in range(spec.windows_per_storey):
            wx = L / (spec.windows_per_storey + 1) * (wi + 1)
            _mk_window(model, body, storey, mats, spec,
                       f"Cửa sổ W{wi+1} T{s_idx+1}",
                       wx - 600, W - wt, 1200, 1500,
                       wall_z + spec.window_sill_height)

        # --- Stairs (inside building, not overlapping walls) ---
        for sti in range(spec.num_staircases):
            stx = L - wt - 2600 if sti == 0 else wt + 200
            _mk_stair(model, body, storey, spec, f"Thang CT{sti+1} T{s_idx+1}",
                      stx, W / 2 - 1000, 2200, 1000, spec.storey_height)

        # --- Footings (ground floor only, below slab) ---
        if s_idx == 0 and spec.has_foundation:
            for ci, (cx, cy) in enumerate(col_grid):
                _mk_footing(model, body, storey, mats, spec,
                            f"Móng M{ci+1}", cx, cy)

    # Roof slab (offset to overhang)
    if storeys:
        _mk_slab(model, body, storeys[-1], mats, spec, "Mái",
                 L + 600, W + 600, 250)

    model.write(filepath)
    logger.info("ifc_v2_generated", filepath=filepath, storeys=spec.num_storeys,
                schema="IFC4", engine="ifcopenshell_api")
    return filepath


# ===== Materials =====

def _create_materials(model, spec):
    mats = {}
    for name in {spec.wall_material, spec.column_material, spec.slab_material,
                 spec.beam_material, spec.window_material, "Vữa trát"}:
        mats[name] = run("material.add_material", model, name=name)

    wall_set = run("material.add_material_set", model, name="Tường hoàn thiện",
                   set_type="IfcMaterialLayerSet")
    plaster = 15.0
    brick = spec.wall_thickness - 2 * plaster

    l1 = run("material.add_layer", model, layer_set=wall_set, material=mats["Vữa trát"])
    l1.LayerThickness = plaster
    l1.Name = "Trát ngoài"

    l2 = run("material.add_layer", model, layer_set=wall_set, material=mats[spec.wall_material])
    l2.LayerThickness = brick
    l2.Name = "Gạch xây"

    l3 = run("material.add_layer", model, layer_set=wall_set, material=mats["Vữa trát"])
    l3.LayerThickness = plaster
    l3.Name = "Trát trong"

    mats["_wall_set"] = wall_set
    return mats


# ===== Element builders =====

def _mk_wall(model, body, storey, mats, spec, name, x, y, length, height, thickness, is_ext, z=0):
    wall = run("root.create_entity", model, ifc_class="IfcWall", name=name,
               predefined_type="STANDARD")
    rep = run("geometry.add_wall_representation", model, context=body,
              length=length, height=height, thickness=thickness)
    run("geometry.assign_representation", model, product=wall, representation=rep)
    run("geometry.edit_object_placement", model, product=wall, matrix=_mat4(x, y, z))
    run("spatial.assign_container", model, relating_structure=storey, products=[wall])
    run("material.assign_material", model, products=[wall],
        material=mats["_wall_set"], type="IfcMaterialLayerSetUsage")
    pset = run("pset.add_pset", model, product=wall, name="Pset_WallCommon")
    run("pset.edit_pset", model, pset=pset, properties={
        "IsExternal": is_ext, "FireRating": "REI 120", "LoadBearing": True})
    return wall


def _mk_column(model, body, storey, mats, spec, name, cx, cy, height):
    col = run("root.create_entity", model, ifc_class="IfcColumn", name=name)
    profile = run("profile.add_parameterized_profile", model,
                  ifc_class="IfcRectangleProfileDef")
    profile.XDim = spec.column_size
    profile.YDim = spec.column_size
    rep = run("geometry.add_profile_representation", model, context=body,
              profile=profile, depth=height)
    run("geometry.assign_representation", model, product=col, representation=rep)
    run("geometry.edit_object_placement", model, product=col, matrix=_mat4(cx, cy, 0))
    run("spatial.assign_container", model, relating_structure=storey, products=[col])
    run("material.assign_material", model, products=[col], material=mats[spec.column_material])
    pset = run("pset.add_pset", model, product=col, name="Pset_ColumnCommon")
    run("pset.edit_pset", model, pset=pset, properties={"LoadBearing": True})
    return col


def _mk_beams(model, body, storey, mats, spec, col_grid, s_idx):
    sx, sy = spec.column_spacing_x, spec.column_spacing_y
    L, W = spec.footprint_length, spec.footprint_width
    nx = max(2, int(L / sx) + 1)
    ny = max(2, int(W / sy) + 1)
    bi = 0

    # X-direction beams
    for j in range(ny):
        cz = min(j * sy, W)
        for i in range(nx - 1):
            x1 = min(i * sx, L)
            x2 = min((i + 1) * sx, L)
            bl = x2 - x1
            if bl > 500:
                bi += 1
                _mk_beam(model, body, storey, mats, spec,
                         f"Dầm BX{bi} T{s_idx+1}", x1, cz, bl, 0)

    # Y-direction beams
    for i in range(nx):
        cx = min(i * sx, L)
        for j in range(ny - 1):
            y1 = min(j * sy, W)
            y2 = min((j + 1) * sy, W)
            bl = y2 - y1
            if bl > 500:
                bi += 1
                _mk_beam(model, body, storey, mats, spec,
                         f"Dầm BY{bi} T{s_idx+1}", cx, y1, bl, math.pi / 2)


def _mk_beam(model, body, storey, mats, spec, name, x, y, length, angle):
    beam = run("root.create_entity", model, ifc_class="IfcBeam", name=name)
    profile = run("profile.add_parameterized_profile", model,
                  ifc_class="IfcRectangleProfileDef")
    profile.XDim = spec.beam_width
    profile.YDim = spec.beam_height
    rep = run("geometry.add_profile_representation", model, context=body,
              profile=profile, depth=length)
    run("geometry.assign_representation", model, product=beam, representation=rep)

    beam_z = spec.storey_height - spec.beam_height
    run("geometry.edit_object_placement", model, product=beam,
        matrix=_mat4_rz(x, y, beam_z, angle))
    run("spatial.assign_container", model, relating_structure=storey, products=[beam])
    run("material.assign_material", model, products=[beam], material=mats[spec.beam_material])
    pset = run("pset.add_pset", model, product=beam, name="Pset_BeamCommon")
    run("pset.edit_pset", model, pset=pset, properties={"LoadBearing": True, "Span": length})
    return beam


def _mk_slab(model, body, storey, mats, spec, name, length, width, thickness):
    slab = run("root.create_entity", model, ifc_class="IfcSlab", name=name,
               predefined_type="FLOOR")
    polyline = [(0.0, 0.0), (length, 0.0), (length, width), (0.0, width), (0.0, 0.0)]
    rep = run("geometry.add_slab_representation", model, context=body,
              depth=thickness, polyline=polyline)
    run("geometry.assign_representation", model, product=slab, representation=rep)
    run("geometry.edit_object_placement", model, product=slab, matrix=_mat4(0, 0, 0))
    run("spatial.assign_container", model, relating_structure=storey, products=[slab])
    run("material.assign_material", model, products=[slab], material=mats[spec.slab_material])
    return slab


def _mk_door(model, body, storey, spec, name, x, y, width, height, z=0):
    door = run("root.create_entity", model, ifc_class="IfcDoor", name=name)
    lining = {"LiningDepth": spec.wall_thickness, "LiningThickness": 50.0,
              "ThresholdDepth": 100.0, "ThresholdThickness": 25.0}
    rep = run("geometry.add_door_representation", model, context=body,
              overall_height=height, overall_width=width,
              lining_properties=lining)
    run("geometry.assign_representation", model, product=door, representation=rep)
    run("geometry.edit_object_placement", model, product=door, matrix=_mat4(x, y, z))
    run("spatial.assign_container", model, relating_structure=storey, products=[door])
    pset = run("pset.add_pset", model, product=door, name="Pset_DoorCommon")
    run("pset.edit_pset", model, pset=pset, properties={"IsExternal": False, "FireRating": "EI 60"})
    return door


def _mk_window(model, body, storey, mats, spec, name, x, y, width, height, sill):
    win = run("root.create_entity", model, ifc_class="IfcWindow", name=name)
    lining = {"LiningDepth": spec.wall_thickness * 0.5, "LiningThickness": 50.0}
    rep = run("geometry.add_window_representation", model, context=body,
              overall_height=height, overall_width=width,
              lining_properties=lining)
    run("geometry.assign_representation", model, product=win, representation=rep)
    run("geometry.edit_object_placement", model, product=win, matrix=_mat4(x, y, sill))
    run("spatial.assign_container", model, relating_structure=storey, products=[win])
    run("material.assign_material", model, products=[win], material=mats[spec.window_material])
    return win


def _mk_stair(model, body, storey, spec, name, x, y, sw, sd, height):
    stair = run("root.create_entity", model, ifc_class="IfcStair", name=name,
                predefined_type="TWO_STRAIGHT_RUN_STAIR")
    profile = run("profile.add_parameterized_profile", model,
                  ifc_class="IfcRectangleProfileDef")
    profile.XDim = sw
    profile.YDim = sd
    rep = run("geometry.add_profile_representation", model, context=body,
              profile=profile, depth=height)
    run("geometry.assign_representation", model, product=stair, representation=rep)
    run("geometry.edit_object_placement", model, product=stair, matrix=_mat4(x, y, 0))
    run("spatial.assign_container", model, relating_structure=storey, products=[stair])
    return stair


def _mk_footing(model, body, storey, mats, spec, name, cx, cy):
    footing = run("root.create_entity", model, ifc_class="IfcFooting", name=name,
                  predefined_type="PAD_FOOTING")
    fs = spec.column_size * 2.5
    profile = run("profile.add_parameterized_profile", model,
                  ifc_class="IfcRectangleProfileDef")
    profile.XDim = fs
    profile.YDim = fs
    rep = run("geometry.add_profile_representation", model, context=body,
              profile=profile, depth=spec.footing_depth)
    run("geometry.assign_representation", model, product=footing, representation=rep)
    run("geometry.edit_object_placement", model, product=footing,
        matrix=_mat4(cx, cy, -spec.footing_depth))
    run("spatial.assign_container", model, relating_structure=storey, products=[footing])
    run("material.assign_material", model, products=[footing], material=mats[spec.column_material])
    return footing


# ===== Helpers =====

def _auto_column_grid(spec):
    positions = []
    sx, sy = spec.column_spacing_x, spec.column_spacing_y
    L, W = spec.footprint_length, spec.footprint_width
    nx, ny = max(2, int(L / sx) + 1), max(2, int(W / sy) + 1)
    for i in range(nx):
        for j in range(ny):
            positions.append((min(i * sx, L), min(j * sy, W)))
    return positions


def _mat4(x, y, z):
    return np.array([[1,0,0,x],[0,1,0,y],[0,0,1,z],[0,0,0,1]], dtype=float)


def _mat4_rz(x, y, z, angle):
    c, s = math.cos(angle), math.sin(angle)
    return np.array([[c,-s,0,x],[s,c,0,y],[0,0,1,z],[0,0,0,1]], dtype=float)
