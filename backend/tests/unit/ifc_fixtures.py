"""Small hand-built IFC4 models for the model-check acceptance tests (task 015). LOCKED.

`build_house(**variant)` returns an in-memory IFC4 model that, with no variant flags, is the
"good" reference: valid schema, every LOD 200 class present, doors/windows in openings, walls
path-connected, columns on grid intersections, one IfcSpace per storey, no clashes, sane extent.
Each keyword flag breaks exactly one property (see VARIANTS).

Geometry: every element is an axis-aligned box (rectangle profile extruded along +Z).
Project length unit is millimetre (like the production generator). ifcopenshell.api geometry
calls take SI metres, so all numbers below are metres; IfcRectangleProfileDef dims are written
raw, so they are converted to project units (mm) by hand.

Plan (metres), storey T1 at z=0, storey T2 at z=3.5:
  grid U axes x=0, x=6; V axes y=0, y=8          columns 0.3x0.3 at the 4 intersections, z 0.2-3.2
  slab T1 0..6 x 0..8, z 0-0.2                    footing 1x1 at (0,0), z -0.5-0
  wall W1 x 0.15-5.85, y 0-0.2, z 0.2-3.2         door in W1 x 2.0-2.9, z 0.2-2.3
  wall W2 x 5.9-6.1, y 0.15-7.85, z 0.2-3.2       window in W2 y 3.0-4.2, z 1.1-2.3
  beam x 0.15-5.85, y 7.9-8.1, z 2.8-3.2          stair x 1-2, y 5-7.8, z 0.2-1.7
  slab T2 0..6 x 0..8, z 3.5-3.7                  railing x 0.15-5.85, y 7.9-7.95, z 3.7-4.8
  roof 0..6 x 0..8, z 4.8-5.0                     spaces: one per storey (excluded from clashes)
Faces may touch; nothing interpenetrates.
"""

import numpy as np
import ifcopenshell
import ifcopenshell.api

run = ifcopenshell.api.run

VARIANTS = {
    "no_openings": "door/window placed in the walls without IfcOpeningElement/filling",
    "no_connection": "W1 and W2 are not path-connected",
    "column_off_grid": "column C2 moved 0.1 m in +x off the grid intersection (6,0)",
    "no_grid": "no IfcGrid in the model",
    "no_stair_railing_roof": "IfcStair, IfcRailing and IfcRoof left out",
    "no_space_t2": "storey T2 has no IfcSpace",
    "far_stair": "stair placed at x = 7800 m (the production placement-scale bug)",
    "stair_into_wall": "stair moved to y 0.1-2.9 so it interpenetrates W1",
    "invalid_proxy": "one IfcBuildingElementProxy created without its required GlobalId",
}


def _mat(x: float, y: float, z: float) -> np.ndarray:
    m = np.eye(4)
    m[:3, 3] = (x, y, z)
    return m


def _box(model, body, storey, ifc_class, name, x0, x1, y0, y1, z0, z1, *, contain=True, **kw):
    """Axis-aligned box element spanning [x0,x1]x[y0,y1]x[z0,z1] metres."""
    el = run("root.create_entity", model, ifc_class=ifc_class, name=name, **kw)
    scale = 1000.0  # m -> mm for the raw profile entity
    profile = model.create_entity(
        "IfcRectangleProfileDef", ProfileType="AREA",
        XDim=(x1 - x0) * scale, YDim=(y1 - y0) * scale,
    )
    rep = run("geometry.add_profile_representation", model, context=body, profile=profile, depth=z1 - z0)
    run("geometry.assign_representation", model, product=el, representation=rep)
    run("geometry.edit_object_placement", model, product=el, matrix=_mat((x0 + x1) / 2, (y0 + y1) / 2, z0))
    if contain and not el.is_a("IfcOpeningElement"):
        run("spatial.assign_container", model, relating_structure=storey, products=[el])
    return el


def _grid(model, storey, us, vs):
    grid = run("root.create_entity", model, ifc_class="IfcGrid", name="Lưới trục")
    run("geometry.edit_object_placement", model, product=grid, matrix=_mat(0, 0, 0))
    run("spatial.assign_container", model, relating_structure=storey, products=[grid])

    def axis(tag, p0, p1):
        pts = [model.createIfcCartesianPoint([c * 1000.0 for c in p]) for p in (p0, p1)]
        return model.create_entity("IfcGridAxis", AxisTag=tag, AxisCurve=model.createIfcPolyline(pts), SameSense=True)

    grid.UAxes = [axis(f"{i + 1}", (u, -1.0), (u, 9.0)) for i, u in enumerate(us)]
    grid.VAxes = [axis(chr(65 + i), (-1.0, v), (7.0, v)) for i, v in enumerate(vs)]
    return grid


def build_house(**variant) -> ifcopenshell.file:
    unknown = set(variant) - set(VARIANTS)
    assert not unknown, f"unknown variant(s): {unknown}"
    v = {k: bool(variant.get(k)) for k in VARIANTS}

    model = ifcopenshell.file(schema="IFC4")
    project = run("root.create_entity", model, ifc_class="IfcProject", name="Fixture")
    run("unit.assign_unit", model, length={"is_metric": True, "raw": "MILLIMETERS"})
    ctx = run("context.add_context", model, context_type="Model")
    body = run("context.add_context", model, context_type="Model", context_identifier="Body",
               target_view="MODEL_VIEW", parent=ctx)

    site = run("root.create_entity", model, ifc_class="IfcSite", name="Site")
    building = run("root.create_entity", model, ifc_class="IfcBuilding", name="Nhà mẫu")
    run("aggregate.assign_object", model, relating_object=project, products=[site])
    run("aggregate.assign_object", model, relating_object=site, products=[building])
    storeys = []
    for name, elev in (("T1", 0.0), ("T2", 3.5)):
        st = run("root.create_entity", model, ifc_class="IfcBuildingStorey", name=name)
        run("geometry.edit_object_placement", model, product=st, matrix=_mat(0, 0, 0))
        st.Elevation = elev * 1000.0
        run("aggregate.assign_object", model, relating_object=building, products=[st])
        storeys.append(st)
    t1, t2 = storeys

    if not v["no_grid"]:
        _grid(model, t1, us=(0.0, 6.0), vs=(0.0, 8.0))

    for i, (cx, cy) in enumerate(((0, 0), (6, 0), (0, 8), (6, 8))):
        if i == 1 and v["column_off_grid"]:
            cx += 0.1
        _box(model, body, t1, "IfcColumn", f"C{i + 1}", cx - 0.15, cx + 0.15, cy - 0.15, cy + 0.15, 0.2, 3.2)

    _box(model, body, t1, "IfcFooting", "F1", -0.5, 0.5, -0.5, 0.5, -0.5, 0.0, predefined_type="PAD_FOOTING")
    _box(model, body, t1, "IfcSlab", "S1", 0, 6, 0, 8, 0, 0.2, predefined_type="FLOOR")
    w1 = _box(model, body, t1, "IfcWall", "W1", 0.15, 5.85, 0, 0.2, 0.2, 3.2)
    w2 = _box(model, body, t1, "IfcWall", "W2", 5.9, 6.1, 0.15, 7.85, 0.2, 3.2)
    if not v["no_connection"]:
        run("geometry.connect_path", model, relating_element=w1, related_element=w2,
            relating_connection="ATEND", related_connection="ATSTART")

    door = _box(model, body, t1, "IfcDoor", "D1", 2.0, 2.9, 0.05, 0.15, 0.2, 2.3)
    win = _box(model, body, t1, "IfcWindow", "WIN1", 5.95, 6.05, 3.0, 4.2, 1.1, 2.3)
    if not v["no_openings"]:
        o1 = _box(model, body, t1, "IfcOpeningElement", "O1", 2.0, 2.9, -0.05, 0.25, 0.2, 2.3, contain=False)
        run("feature.add_feature", model, feature=o1, element=w1)
        run("feature.add_filling", model, opening=o1, element=door)
        o2 = _box(model, body, t1, "IfcOpeningElement", "O2", 5.85, 6.15, 3.0, 4.2, 1.1, 2.3, contain=False)
        run("feature.add_feature", model, feature=o2, element=w2)
        run("feature.add_filling", model, opening=o2, element=win)

    _box(model, body, t1, "IfcBeam", "B1", 0.15, 5.85, 7.9, 8.1, 2.8, 3.2)
    if not v["no_stair_railing_roof"]:
        if v["far_stair"]:
            _box(model, body, t1, "IfcStair", "ST1", 7800.0, 7801.0, 5.0, 7.8, 0.2, 1.7)
        elif v["stair_into_wall"]:
            _box(model, body, t1, "IfcStair", "ST1", 1.0, 2.0, 0.1, 2.9, 0.2, 1.7)
        else:
            _box(model, body, t1, "IfcStair", "ST1", 1.0, 2.0, 5.0, 7.8, 0.2, 1.7)

    _box(model, body, t2, "IfcSlab", "S2", 0, 6, 0, 8, 3.5, 3.7, predefined_type="FLOOR")
    if not v["no_stair_railing_roof"]:
        _box(model, body, t2, "IfcRailing", "R1", 0.15, 5.85, 7.9, 7.95, 3.7, 4.8)
        _box(model, body, t2, "IfcRoof", "RF1", 0, 6, 0, 8, 4.8, 5.0)

    for st, z0, z1, skip in ((t1, 0.2, 3.5, False), (t2, 3.7, 4.8, v["no_space_t2"])):
        if skip:
            continue
        sp = _box(model, body, st, "IfcSpace", f"P-{st.Name}", 0.2, 5.8, 0.25, 7.8, z0, z1, contain=False)
        run("aggregate.assign_object", model, relating_object=st, products=[sp])

    if v["invalid_proxy"]:
        model.create_entity("IfcBuildingElementProxy", Name="broken")  # GlobalId missing on purpose
    return model
