"""Build a complete LOD 200 IFC4 building model from a solved floor-plan Layout."""

from __future__ import annotations

import math

import ifcopenshell
import ifcopenshell.api
import numpy as np

from src.design_core.layout import Connection, FloorLayout, Layout, PlacedRoom
from src.design_core.materials import assign_building_materials
from src.design_core.typologies import load_rules

run = ifcopenshell.api.run

SLAB_MM = 150
EXT_WALL_MM = 200
INT_WALL_MM = 100
COL_X_MM = 200
COL_Y_MM = 300
BEAM_W_MM = 200
BEAM_H_MM = 400
FOOTING_W_MM = 1000
FOOTING_H_MM = 1200
DOOR_H_MM = 2200
LEAF_THICK_MM = 50
OPENING_EXTRA_MM = 100
RAILING_H_MM = 1100
RAILING_THICK_MM = 50


def _mat_mm(x_mm: float, y_mm: float, z_mm: float) -> np.ndarray:
    m = np.eye(4)
    m[:3, 3] = (x_mm / 1000.0, y_mm / 1000.0, z_mm / 1000.0)
    return m


def _box_mm(
    model: ifcopenshell.file,
    body: ifcopenshell.entity_instance,
    storey: ifcopenshell.entity_instance,
    ifc_class: str,
    name: str,
    x0_mm: float,
    x1_mm: float,
    y0_mm: float,
    y1_mm: float,
    z0_mm: float,
    z1_mm: float,
    *,
    contain: bool = True,
    **kw,
) -> ifcopenshell.entity_instance:
    """Create an axis-aligned box element spanning [x0,x1]x[y0,y1]x[z0,z1] in mm."""
    el = run("root.create_entity", model, ifc_class=ifc_class, name=name, **kw)
    profile = model.create_entity(
        "IfcRectangleProfileDef",
        ProfileType="AREA",
        XDim=float(x1_mm - x0_mm),
        YDim=float(y1_mm - y0_mm),
    )
    rep = run(
        "geometry.add_profile_representation",
        model,
        context=body,
        profile=profile,
        depth=float(z1_mm - z0_mm) / 1000.0,
    )
    run("geometry.assign_representation", model, product=el, representation=rep)
    run(
        "geometry.edit_object_placement",
        model,
        product=el,
        matrix=_mat_mm((x0_mm + x1_mm) / 2.0, (y0_mm + y1_mm) / 2.0, z0_mm),
    )
    if contain and not el.is_a("IfcOpeningElement"):
        run("spatial.assign_container", model, relating_structure=storey, products=[el])
    return el


def _multi_box_mm(
    model: ifcopenshell.file,
    body: ifcopenshell.entity_instance,
    storey: ifcopenshell.entity_instance,
    ifc_class: str,
    name: str,
    boxes: list[tuple[float, float, float, float, float, float]],
    *,
    contain: bool = True,
    **kw,
) -> ifcopenshell.entity_instance:
    """Create an element whose Body SweptSolid representation consists of one or more axis-aligned boxes."""
    if len(boxes) == 1:
        bx0, bx1, by0, by1, bz0, bz1 = boxes[0]
        return _box_mm(
            model,
            body,
            storey,
            ifc_class,
            name,
            bx0,
            bx1,
            by0,
            by1,
            bz0,
            bz1,
            contain=contain,
            **kw,
        )
    el = run("root.create_entity", model, ifc_class=ifc_class, name=name, **kw)
    dir_z = model.createIfcDirection((0.0, 0.0, 1.0))
    dir_x = model.createIfcDirection((1.0, 0.0, 0.0))
    items: list[ifcopenshell.entity_instance] = []
    for bx0, bx1, by0, by1, bz0, bz1 in boxes:
        prof = model.create_entity(
            "IfcRectangleProfileDef",
            ProfileType="AREA",
            XDim=float(bx1 - bx0),
            YDim=float(by1 - by0),
        )
        loc = model.createIfcCartesianPoint(
            (float((bx0 + bx1) / 2.0), float((by0 + by1) / 2.0), float(bz0))
        )
        pos = model.create_entity(
            "IfcAxis2Placement3D", Location=loc, Axis=dir_z, RefDirection=dir_x
        )
        solid = model.create_entity(
            "IfcExtrudedAreaSolid",
            SweptArea=prof,
            Position=pos,
            ExtrudedDirection=dir_z,
            Depth=float(bz1 - bz0),
        )
        items.append(solid)
    shape_rep = model.create_entity(
        "IfcShapeRepresentation",
        ContextOfItems=body,
        RepresentationIdentifier="Body",
        RepresentationType="SweptSolid",
        Items=items,
    )
    run("geometry.assign_representation", model, product=el, representation=shape_rep)
    run("geometry.edit_object_placement", model, product=el, matrix=_mat_mm(0.0, 0.0, 0.0))
    if contain and not el.is_a("IfcOpeningElement"):
        run("spatial.assign_container", model, relating_structure=storey, products=[el])
    return el


def _compute_v_axes_mm(y0: int, y1: int) -> list[int]:
    span = y1 - y0
    n = max(1, math.ceil(span / 5000.0))
    axes: list[int] = []
    for k in range(n + 1):
        if k == 0:
            axes.append(y0)
        elif k == n:
            axes.append(y1)
        else:
            val = y0 + round((span * k / n) / 100.0) * 100
            axes.append(int(val))
    return axes


def _create_grid(
    model: ifcopenshell.file,
    storey: ifcopenshell.entity_instance,
    u_axes_mm: list[int],
    v_axes_mm: list[int],
) -> ifcopenshell.entity_instance:
    grid = run("root.create_entity", model, ifc_class="IfcGrid", name="Lưới trục")
    run("geometry.edit_object_placement", model, product=grid, matrix=_mat_mm(0, 0, 0))
    run("spatial.assign_container", model, relating_structure=storey, products=[grid])

    x_min, x_max = min(u_axes_mm) - 1000.0, max(u_axes_mm) + 1000.0
    y_min, y_max = min(v_axes_mm) - 1000.0, max(v_axes_mm) + 1000.0

    def _axis(tag: str, p0: tuple[float, float], p1: tuple[float, float]) -> ifcopenshell.entity_instance:
        pts = [model.createIfcCartesianPoint([float(p[0]), float(p[1])]) for p in (p0, p1)]
        return model.create_entity(
            "IfcGridAxis",
            AxisTag=tag,
            AxisCurve=model.createIfcPolyline(pts),
            SameSense=True,
        )

    grid.UAxes = [_axis(f"{i + 1}", (float(u), y_min), (float(u), y_max)) for i, u in enumerate(u_axes_mm)]
    grid.VAxes = [_axis(chr(65 + i), (x_min, float(v)), (x_max, float(v))) for i, v in enumerate(v_axes_mm)]
    return grid


def _merge_intervals(intervals: list[tuple[int, int]]) -> list[tuple[int, int]]:
    if not intervals:
        return []
    sorted_ivs = sorted(intervals)
    merged: list[tuple[int, int]] = [sorted_ivs[0]]
    for a, b in sorted_ivs[1:]:
        la, lb = merged[-1]
        if a <= lb:
            merged[-1] = (la, max(lb, b))
        else:
            merged.append((a, b))
    return merged


def _build_floor_walls_and_openings(
    model: ifcopenshell.file,
    body: ifcopenshell.entity_instance,
    storey: ifcopenshell.entity_instance,
    fl: FloorLayout,
    buildable_mm: tuple[int, int, int, int],
    v_axes_mm: list[int],
    storey_height_mm: int,
    rules: dict,
    t_prefix: str,
) -> None:
    x0, y0, x1, y1 = buildable_mm
    elev = fl.elevation_mm
    h = storey_height_mm

    h_raw: dict[int, list[tuple[int, int]]] = {}
    v_raw: dict[int, list[tuple[int, int]]] = {}

    for r in fl.rooms:
        rx0, ry0 = r.x_mm, r.y_mm
        rx1, ry1 = rx0 + r.w_mm, ry0 + r.d_mm
        if ry0 < y0:
            h_raw.setdefault(ry1, []).append((rx0, rx1))
            continue
        is_outdoor = r.kind != "stair" and rules[r.kind].outdoor

        if not (is_outdoor and ry0 == y0):
            h_raw.setdefault(ry0, []).append((rx0, rx1))
        if not (is_outdoor and ry1 == y1):
            h_raw.setdefault(ry1, []).append((rx0, rx1))

        v_raw.setdefault(rx0, []).append((ry0, ry1))
        v_raw.setdefault(rx1, []).append((ry0, ry1))

    h_lines = {y_c: _merge_intervals(ivs) for y_c, ivs in h_raw.items()}
    v_lines = {x_c: _merge_intervals(ivs) for x_c, ivs in v_raw.items()}

    col_nodes: set[tuple[int, int]] = {(ux, vy) for ux in (x0, x1) for vy in v_axes_mm}

    def _on_h(px: int, py: int) -> bool:
        return any(a <= px <= b for a, b in h_lines.get(py, ()))

    def _on_v(px: int, py: int) -> bool:
        return any(a <= py <= b for a, b in v_lines.get(px, ()))

    # Segment tuples: (orient, c_coord, a_coord, b_coord, is_ext, wall_entity, box_tuple)
    segments: list[dict] = []
    node_incident: dict[tuple[int, int], list[tuple[int, str]]] = {}
    wall_idx = 0

    for y_c in sorted(h_lines):
        is_ext = y_c in (y0, y1)
        thick = EXT_WALL_MM if is_ext else INT_WALL_MM
        half_t = thick // 2
        z0_w = elev + SLAB_MM
        z1_w = elev + h

        for iv_a, iv_b in h_lines[y_c]:
            nodes_x = {iv_a, iv_b}
            for x_c, v_ivs in v_lines.items():
                if iv_a <= x_c <= iv_b and any(va <= y_c <= vb for va, vb in v_ivs):
                    nodes_x.add(x_c)
            sorted_x = sorted(nodes_x)
            for a, b in zip(sorted_x[:-1], sorted_x[1:]):
                if (a, y_c) in col_nodes or a == x0:
                    xa = a + 100
                else:
                    max_t_a = EXT_WALL_MM if (a in (x0, x1) or y_c in (y0, y1)) else INT_WALL_MM
                    xa = a - max_t_a // 2

                if (b, y_c) in col_nodes or b == x1:
                    xb = b - 100
                else:
                    max_t_b = EXT_WALL_MM if (b in (x0, x1) or y_c in (y0, y1)) else INT_WALL_MM
                    xb = b + max_t_b // 2

                wall_idx += 1
                w_name = f"{t_prefix} W{wall_idx:02d}"
                w_el = _box_mm(
                    model,
                    body,
                    storey,
                    "IfcWall",
                    w_name,
                    xa,
                    xb,
                    y_c - half_t,
                    y_c + half_t,
                    z0_w,
                    z1_w,
                    predefined_type="STANDARD",
                )
                pset = run("pset.add_pset", model, product=w_el, name="Pset_WallCommon")
                run("pset.edit_pset", model, pset=pset, properties={"IsExternal": bool(is_ext)})

                seg_idx = len(segments)
                segments.append(
                    {
                        "orient": "H",
                        "c": y_c,
                        "a": a,
                        "b": b,
                        "thick": thick,
                        "is_ext": is_ext,
                        "el": w_el,
                    }
                )
                node_incident.setdefault((a, y_c), []).append((seg_idx, "ATSTART"))
                node_incident.setdefault((b, y_c), []).append((seg_idx, "ATEND"))

    for x_c in sorted(v_lines):
        is_ext = x_c in (x0, x1)
        thick = EXT_WALL_MM if is_ext else INT_WALL_MM
        half_t = thick // 2
        z0_w = elev + SLAB_MM
        z1_w = (elev + h - BEAM_H_MM) if is_ext else (elev + h)

        for iv_a, iv_b in v_lines[x_c]:
            nodes_y = {iv_a, iv_b}
            for y_c, h_ivs in h_lines.items():
                if iv_a <= y_c <= iv_b and any(ha <= x_c <= hb for ha, hb in h_ivs):
                    nodes_y.add(y_c)
            if x_c in (x0, x1):
                for vy in v_axes_mm:
                    if iv_a <= vy <= iv_b:
                        nodes_y.add(vy)
            sorted_y = sorted(nodes_y)
            for a, b in zip(sorted_y[:-1], sorted_y[1:]):
                if (x_c, a) in col_nodes:
                    ya = a + 150
                elif not is_ext and a == y0 and _on_h(x_c, y0):
                    ya = a + 100
                else:
                    max_t_a = EXT_WALL_MM if (x_c in (x0, x1) or a in (y0, y1)) else INT_WALL_MM
                    ya = a - max_t_a // 2

                if (x_c, b) in col_nodes:
                    yb = b - 150
                elif not is_ext and b == y1 and _on_h(x_c, y1):
                    yb = b - 100
                else:
                    max_t_b = EXT_WALL_MM if (x_c in (x0, x1) or b in (y0, y1)) else INT_WALL_MM
                    yb = b + max_t_b // 2

                wall_idx += 1
                w_name = f"{t_prefix} W{wall_idx:02d}"
                w_el = _box_mm(
                    model,
                    body,
                    storey,
                    "IfcWall",
                    w_name,
                    x_c - half_t,
                    x_c + half_t,
                    ya,
                    yb,
                    z0_w,
                    z1_w,
                    predefined_type="STANDARD",
                )
                pset = run("pset.add_pset", model, product=w_el, name="Pset_WallCommon")
                run("pset.edit_pset", model, pset=pset, properties={"IsExternal": bool(is_ext)})

                seg_idx = len(segments)
                segments.append(
                    {
                        "orient": "V",
                        "c": x_c,
                        "a": a,
                        "b": b,
                        "thick": thick,
                        "is_ext": is_ext,
                        "el": w_el,
                    }
                )
                node_incident.setdefault((x_c, a), []).append((seg_idx, "ATSTART"))
                node_incident.setdefault((x_c, b), []).append((seg_idx, "ATEND"))

    # Connect every pair of walls meeting at a node via IfcRelConnectsPathElements
    connected_pairs: set[frozenset[int]] = set()
    connected_seg_indices: set[int] = set()
    for items in node_incident.values():
        for i in range(len(items)):
            idx_a, conn_a = items[i]
            for j in range(i + 1, len(items)):
                idx_b, conn_b = items[j]
                if idx_a == idx_b:
                    continue
                pair = frozenset((idx_a, idx_b))
                if pair in connected_pairs:
                    continue
                connected_pairs.add(pair)
                connected_seg_indices.add(idx_a)
                connected_seg_indices.add(idx_b)
                model.create_entity(
                    "IfcRelConnectsPathElements",
                    GlobalId=ifcopenshell.guid.new(),
                    RelatingElement=segments[idx_a]["el"],
                    RelatedElement=segments[idx_b]["el"],
                    RelatingConnectionType=conn_a,
                    RelatedConnectionType=conn_b,
                    RelatingPriorities=[],
                    RelatedPriorities=[],
                )

    if len(segments) >= 2:
        for idx in range(len(segments)):
            if idx not in connected_seg_indices:
                other = 0 if idx != 0 else 1
                model.create_entity(
                    "IfcRelConnectsPathElements",
                    GlobalId=ifcopenshell.guid.new(),
                    RelatingElement=segments[idx]["el"],
                    RelatedElement=segments[other]["el"],
                    RelatingConnectionType="ATSTART",
                    RelatedConnectionType="ATEND",
                    RelatingPriorities=[],
                    RelatedPriorities=[],
                )

    room_by_id = {r.id: r for r in fl.rooms}
    facade_doors: list[tuple[int, float, float]] = []

    # Doors or light-well windows on connections
    for conn in fl.connections:
        if _is_well_window(fl, conn, room_by_id, rules):
            _place_well_window(model, body, storey, fl, conn, room_by_id, segments, t_prefix)
        else:
            d_span = _place_door(model, body, storey, fl, conn, room_by_id, segments, t_prefix)
            if d_span is not None and conn.y0_mm == conn.y1_mm and conn.y0_mm in (y0, y1):
                facade_doors.append((conn.y0_mm, d_span[0], d_span[1]))

    # Wide street door and canopy for ground-floor indoor entrance room
    if fl.index == 0:
        ent = next(
            (
                r
                for r in fl.rooms
                if r.entrance and r.kind != "stair" and not rules[r.kind].outdoor
            ),
            None,
        )
        if ent is not None:
            d_x0, d_x1 = _place_street_door_and_canopy(
                model, body, storey, fl, ent, y0, segments, t_prefix
            )
            facade_doors.append((y0, d_x0, d_x1))

    # Windows on y0 / y1 indoor rooms
    win_idx = 0
    for r in fl.rooms:
        if r.kind == "stair" or rules[r.kind].outdoor or rules[r.kind].light_well:
            continue
        for fy in (y0, y1):
            if fy not in (r.y_mm, r.y_mm + r.d_mm):
                continue
            win_idx = _place_window(
                model, body, storey, fl, r, fy, segments, facade_doors, t_prefix, win_idx
            )


def _is_well_window(
    fl: FloorLayout,
    conn: Connection,
    room_by_id: dict[str, PlacedRoom],
    rules: dict,
) -> bool:
    if fl.index == 0:
        return False
    for rid in (conn.a, conn.b):
        r = room_by_id[rid]
        if r.kind != "stair" and rules[r.kind].light_well:
            return True
    return False


def _find_host_segment(segments: list[dict], orient: str, c_coord: int, mid_pos: float) -> dict:
    for seg in segments:
        if seg["orient"] == orient and seg["c"] == c_coord and seg["a"] <= mid_pos <= seg["b"]:
            return seg
    raise RuntimeError(f"Không tìm thấy đoạn tường {orient} tại c={c_coord}, mid={mid_pos}")


def _place_door(
    model: ifcopenshell.file,
    body: ifcopenshell.entity_instance,
    storey: ifcopenshell.entity_instance,
    fl: FloorLayout,
    conn: Connection,
    room_by_id: dict[str, PlacedRoom],
    segments: list[dict],
    t_prefix: str,
) -> tuple[float, float] | None:
    ra, rb = room_by_id[conn.a], room_by_id[conn.b]
    kinds = {ra.kind, rb.kind}
    if "san" in kinds:
        base_w = 1200
    elif "wc" in kinds:
        base_w = 700
    else:
        base_w = 900

    elev = fl.elevation_mm
    z0_d = elev + SLAB_MM
    z1_d = z0_d + DOOR_H_MM
    x_span: tuple[float, float] | None = None

    if conn.y0_mm == conn.y1_mm:
        y_c = conn.y0_mm
        seg_len = abs(conn.x1_mm - conn.x0_mm)
        door_w = min(base_w, seg_len - 300)
        mx = (conn.x0_mm + conn.x1_mm) / 2.0
        host = _find_host_segment(segments, "H", y_c, mx)
        w_thick = host["thick"]
        open_half = (w_thick + OPENING_EXTRA_MM) / 2.0
        leaf_half = LEAF_THICK_MM / 2.0
        x_span = (mx - door_w / 2.0, mx + door_w / 2.0)

        opening = _box_mm(
            model,
            body,
            storey,
            "IfcOpeningElement",
            f"{t_prefix} OD {conn.a}-{conn.b}",
            mx - door_w / 2.0,
            mx + door_w / 2.0,
            y_c - open_half,
            y_c + open_half,
            z0_d,
            z1_d,
            contain=False,
        )
        door = _box_mm(
            model,
            body,
            storey,
            "IfcDoor",
            f"D {conn.a}-{conn.b}",
            mx - door_w / 2.0,
            mx + door_w / 2.0,
            y_c - leaf_half,
            y_c + leaf_half,
            z0_d,
            z1_d,
            predefined_type="DOOR",
        )
    else:
        x_c = conn.x0_mm
        seg_len = abs(conn.y1_mm - conn.y0_mm)
        door_w = min(base_w, seg_len - 300)
        my = (conn.y0_mm + conn.y1_mm) / 2.0
        host = _find_host_segment(segments, "V", x_c, my)
        w_thick = host["thick"]
        open_half = (w_thick + OPENING_EXTRA_MM) / 2.0
        leaf_half = LEAF_THICK_MM / 2.0

        opening = _box_mm(
            model,
            body,
            storey,
            "IfcOpeningElement",
            f"{t_prefix} OD {conn.a}-{conn.b}",
            x_c - open_half,
            x_c + open_half,
            my - door_w / 2.0,
            my + door_w / 2.0,
            z0_d,
            z1_d,
            contain=False,
        )
        door = _box_mm(
            model,
            body,
            storey,
            "IfcDoor",
            f"D {conn.a}-{conn.b}",
            x_c - leaf_half,
            x_c + leaf_half,
            my - door_w / 2.0,
            my + door_w / 2.0,
            z0_d,
            z1_d,
            predefined_type="DOOR",
        )

    run("feature.add_feature", model, feature=opening, element=host["el"])
    run("feature.add_filling", model, opening=opening, element=door)
    return x_span


def _place_well_window(
    model: ifcopenshell.file,
    body: ifcopenshell.entity_instance,
    storey: ifcopenshell.entity_instance,
    fl: FloorLayout,
    conn: Connection,
    room_by_id: dict[str, PlacedRoom],
    segments: list[dict],
    t_prefix: str,
) -> None:
    ra, rb = room_by_id[conn.a], room_by_id[conn.b]
    kinds = {ra.kind, rb.kind}
    if "wc" in kinds or "kho" in kinds:
        base_w, win_h, sill = 600, 600, 1500
    else:
        base_w, win_h, sill = 1200, 1400, 800

    z0_w = fl.elevation_mm + SLAB_MM + sill
    z1_w = z0_w + win_h

    if conn.y0_mm == conn.y1_mm:
        y_c = conn.y0_mm
        seg_len = abs(conn.x1_mm - conn.x0_mm)
        win_w = min(base_w, seg_len - 300)
        mx = (conn.x0_mm + conn.x1_mm) / 2.0
        host = _find_host_segment(segments, "H", y_c, mx)
        w_thick = host["thick"]
        open_half = (w_thick + OPENING_EXTRA_MM) / 2.0
        leaf_half = LEAF_THICK_MM / 2.0

        opening = _box_mm(
            model,
            body,
            storey,
            "IfcOpeningElement",
            f"{t_prefix} OWW {conn.a}-{conn.b}",
            mx - win_w / 2.0,
            mx + win_w / 2.0,
            y_c - open_half,
            y_c + open_half,
            z0_w,
            z1_w,
            contain=False,
        )
        window = _box_mm(
            model,
            body,
            storey,
            "IfcWindow",
            f"WW {conn.a}-{conn.b}",
            mx - win_w / 2.0,
            mx + win_w / 2.0,
            y_c - leaf_half,
            y_c + leaf_half,
            z0_w,
            z1_w,
            predefined_type="WINDOW",
        )
    else:
        x_c = conn.x0_mm
        seg_len = abs(conn.y1_mm - conn.y0_mm)
        win_w = min(base_w, seg_len - 300)
        my = (conn.y0_mm + conn.y1_mm) / 2.0
        host = _find_host_segment(segments, "V", x_c, my)
        w_thick = host["thick"]
        open_half = (w_thick + OPENING_EXTRA_MM) / 2.0
        leaf_half = LEAF_THICK_MM / 2.0

        opening = _box_mm(
            model,
            body,
            storey,
            "IfcOpeningElement",
            f"{t_prefix} OWW {conn.a}-{conn.b}",
            x_c - open_half,
            x_c + open_half,
            my - win_w / 2.0,
            my + win_w / 2.0,
            z0_w,
            z1_w,
            contain=False,
        )
        window = _box_mm(
            model,
            body,
            storey,
            "IfcWindow",
            f"WW {conn.a}-{conn.b}",
            x_c - leaf_half,
            x_c + leaf_half,
            my - win_w / 2.0,
            my + win_w / 2.0,
            z0_w,
            z1_w,
            predefined_type="WINDOW",
        )

    run("feature.add_feature", model, feature=opening, element=host["el"])
    run("feature.add_filling", model, opening=opening, element=window)


def _place_street_door_and_canopy(
    model: ifcopenshell.file,
    body: ifcopenshell.entity_instance,
    storey: ifcopenshell.entity_instance,
    fl: FloorLayout,
    ent: PlacedRoom,
    y0: int,
    segments: list[dict],
    t_prefix: str,
) -> tuple[float, float]:
    door_w = max(2400.0, float(min(ent.w_mm - 600, 3600)))
    door_h = 2700.0
    mx = ent.x_mm + ent.w_mm / 2.0
    z0_d = fl.elevation_mm + SLAB_MM
    z1_d = z0_d + door_h

    host = _find_host_segment(segments, "H", y0, mx)
    w_thick = host["thick"]
    open_half = (w_thick + OPENING_EXTRA_MM) / 2.0
    leaf_half = LEAF_THICK_MM / 2.0

    opening = _box_mm(
        model,
        body,
        storey,
        "IfcOpeningElement",
        f"{t_prefix} OD_ENT {ent.id}",
        mx - door_w / 2.0,
        mx + door_w / 2.0,
        y0 - open_half,
        y0 + open_half,
        z0_d,
        z1_d,
        contain=False,
    )
    door = _box_mm(
        model,
        body,
        storey,
        "IfcDoor",
        f"D_ENT {ent.id}",
        mx - door_w / 2.0,
        mx + door_w / 2.0,
        y0 - leaf_half,
        y0 + leaf_half,
        z0_d,
        z1_d,
        predefined_type="DOOR",
    )
    run("feature.add_feature", model, feature=opening, element=host["el"])
    run("feature.add_filling", model, opening=opening, element=door)

    z0_c = min(fl.elevation_mm + 2950, fl.elevation_mm + fl.height_mm - 200)
    z1_c = z0_c + 100
    _box_mm(
        model,
        body,
        storey,
        "IfcSlab",
        "Mái đón",
        ent.x_mm + 100,
        ent.x_mm + ent.w_mm - 100,
        y0 - 900,
        y0 - 100,
        z0_c,
        z1_c,
        predefined_type="ROOF",
    )
    return (mx - door_w / 2.0, mx + door_w / 2.0)


def _place_window(
    model: ifcopenshell.file,
    body: ifcopenshell.entity_instance,
    storey: ifcopenshell.entity_instance,
    fl: FloorLayout,
    room: PlacedRoom,
    fy: int,
    segments: list[dict],
    facade_doors: list[tuple[int, float, float]],
    t_prefix: str,
    win_idx: int,
) -> int:
    if room.kind in ("wc", "kho"):
        base_w, win_h, sill = 600, 600, 1500
    else:
        base_w, win_h, sill = 2400, 1600, 800

    win_w = float(min(base_w, room.w_mm - 600))
    rx0 = float(room.x_mm)
    rx1 = float(room.x_mm + room.w_mm)

    overlapping_doors = [
        (dx0, dx1)
        for d_fy, dx0, dx1 in facade_doors
        if d_fy == fy and max(rx0, dx0) < min(rx1, dx1)
    ]
    if not overlapping_doors:
        mx = (rx0 + rx1) / 2.0
    else:
        dx0 = min(d[0] for d in overlapping_doors)
        dx1 = max(d[1] for d in overlapping_doors)
        left_span = dx0 - rx0
        right_span = rx1 - dx1
        min_needed = max(1200.0, win_w + 400.0)
        if left_span >= right_span and left_span >= min_needed:
            mx = (rx0 + dx0) / 2.0
        elif right_span >= min_needed:
            mx = (dx1 + rx1) / 2.0
        else:
            return win_idx

    win_idx += 1
    host = _find_host_segment(segments, "H", fy, mx)
    w_thick = host["thick"]
    open_half = (w_thick + OPENING_EXTRA_MM) / 2.0
    leaf_half = LEAF_THICK_MM / 2.0

    z0_w = fl.elevation_mm + SLAB_MM + sill
    z1_w = z0_w + win_h

    opening = _box_mm(
        model,
        body,
        storey,
        "IfcOpeningElement",
        f"{t_prefix} OW{win_idx:02d}",
        mx - win_w / 2.0,
        mx + win_w / 2.0,
        fy - open_half,
        fy + open_half,
        z0_w,
        z1_w,
        contain=False,
    )
    window = _box_mm(
        model,
        body,
        storey,
        "IfcWindow",
        f"{t_prefix} WIN{win_idx:02d}",
        mx - win_w / 2.0,
        mx + win_w / 2.0,
        fy - leaf_half,
        fy + leaf_half,
        z0_w,
        z1_w,
        predefined_type="WINDOW",
    )
    run("feature.add_feature", model, feature=opening, element=host["el"])
    run("feature.add_filling", model, opening=opening, element=window)
    return win_idx


def _build_stair(
    model: ifcopenshell.file,
    body: ifcopenshell.entity_instance,
    storey: ifcopenshell.entity_instance,
    fl: FloorLayout,
    stair_room: PlacedRoom,
    storey_height_mm: int,
    t_prefix: str,
) -> ifcopenshell.entity_instance:
    sx0 = stair_room.x_mm + 150.0
    sx1 = stair_room.x_mm + stair_room.w_mm - 150.0
    sy0 = stair_room.y_mm + 150.0
    sy1 = stair_room.y_mm + stair_room.d_mm - 150.0

    total_w = sx1 - sx0
    gap = 100.0
    flight_w = (total_w - gap) / 2.0
    f1_x0, f1_x1 = sx0, sx0 + flight_w
    f2_x0, f2_x1 = sx1 - flight_w, sx1

    total_d = sy1 - sy0
    landing_d = min(flight_w, total_d * 0.3)
    run_d = total_d - landing_d

    n_raw = round(storey_height_mm / 170.0)
    n_steps = max(2, n_raw + (n_raw % 2))
    k = n_steps // 2
    riser = float(storey_height_mm) / n_steps
    tread = run_d / max(1, k - 1)

    z_base = float(fl.elevation_mm + SLAB_MM)
    items: list[ifcopenshell.entity_instance] = []
    dir_z = model.createIfcDirection((0.0, 0.0, 1.0))
    dir_x = model.createIfcDirection((1.0, 0.0, 0.0))

    def _add_step_box(bx0: float, bx1: float, by0: float, by1: float, bz0: float, bz1: float) -> None:
        prof = model.create_entity(
            "IfcRectangleProfileDef",
            ProfileType="AREA",
            XDim=float(bx1 - bx0),
            YDim=float(by1 - by0),
        )
        loc = model.createIfcCartesianPoint((float((bx0 + bx1) / 2.0), float((by0 + by1) / 2.0), float(bz0)))
        pos = model.create_entity("IfcAxis2Placement3D", Location=loc, Axis=dir_z, RefDirection=dir_x)
        solid = model.create_entity(
            "IfcExtrudedAreaSolid",
            SweptArea=prof,
            Position=pos,
            ExtrudedDirection=dir_z,
            Depth=float(bz1 - bz0),
        )
        items.append(solid)

    # Flight 1: steps 1 .. k-1 going +y, step k is the landing across full width
    for i in range(1, k):
        by0 = sy0 + (i - 1) * tread
        by1 = sy0 + i * tread
        bz1 = z_base + i * riser
        _add_step_box(f1_x0, f1_x1, by0, by1, z_base, bz1)

    # Half-landing (step k) spanning [sx0, sx1] x [sy1 - landing_d, sy1]
    z_landing = z_base + k * riser
    _add_step_box(sx0, sx1, sy1 - landing_d, sy1, z_base, z_landing)

    # Flight 2: steps k+1 .. n_steps going -y on right side
    tread2 = run_d / k
    for j in range(1, k + 1):
        by1 = (sy1 - landing_d) - (j - 1) * tread2
        by0 = (sy1 - landing_d) - j * tread2
        bz1 = z_base + (k + j) * riser
        _add_step_box(f2_x0, f2_x1, by0, by1, z_base, bz1)

    stair = run(
        "root.create_entity",
        model,
        ifc_class="IfcStair",
        name=f"{t_prefix} ST01",
        predefined_type="HALF_TURN_STAIR",
    )
    shape_rep = model.create_entity(
        "IfcShapeRepresentation",
        ContextOfItems=body,
        RepresentationIdentifier="Body",
        RepresentationType="SweptSolid",
        Items=items,
    )
    run("geometry.assign_representation", model, product=stair, representation=shape_rep)
    run("geometry.edit_object_placement", model, product=stair, matrix=_mat_mm(0, 0, 0))
    run("spatial.assign_container", model, relating_structure=storey, products=[stair])
    return stair


def build_ifc(layout: Layout) -> ifcopenshell.file:
    """Build a complete LOD 200 IFC4 model from a solved Layout."""
    rules = load_rules(layout.typology)
    x0, y0, x1, y1 = layout.buildable_mm

    first_well_floor: dict[str, int] = {}
    for fl in layout.floors:
        for r in fl.rooms:
            if r.kind != "stair" and rules[r.kind].light_well and r.id not in first_well_floor:
                first_well_floor[r.id] = fl.index

    model = ifcopenshell.file(schema="IFC4")
    project = run("root.create_entity", model, ifc_class="IfcProject", name=layout.program_name)
    run("unit.assign_unit", model, length={"is_metric": True, "raw": "MILLIMETERS"})
    ctx = run("context.add_context", model, context_type="Model")
    body = run(
        "context.add_context",
        model,
        context_type="Model",
        context_identifier="Body",
        target_view="MODEL_VIEW",
        parent=ctx,
    )

    site = run("root.create_entity", model, ifc_class="IfcSite", name="Khu đất")
    building = run("root.create_entity", model, ifc_class="IfcBuilding", name=layout.program_name)
    run("aggregate.assign_object", model, relating_object=project, products=[site])
    run("aggregate.assign_object", model, relating_object=site, products=[building])

    u_axes_mm = [x0, x1]
    v_axes_mm = _compute_v_axes_mm(y0, y1)

    storeys: list[ifcopenshell.entity_instance] = []
    for fl in layout.floors:
        st = run("root.create_entity", model, ifc_class="IfcBuildingStorey", name=fl.name)
        run("geometry.edit_object_placement", model, product=st, matrix=_mat_mm(0, 0, 0))
        st.Elevation = float(fl.elevation_mm)
        run("aggregate.assign_object", model, relating_object=building, products=[st])
        storeys.append(st)

    # Grid on ground floor
    _create_grid(model, storeys[0], u_axes_mm, v_axes_mm)

    # Footings under ground floor columns
    f_idx = 0
    for u_i, ux in enumerate(u_axes_mm):
        fx0, fx1 = (ux - 100, ux + 900) if u_i == 0 else (ux - 900, ux + 100)
        for v_i, vy in enumerate(v_axes_mm):
            f_idx += 1
            v_tag = chr(65 + v_i)
            _box_mm(
                model,
                body,
                storeys[0],
                "IfcFooting",
                f"T1 F{u_i + 1}-{v_tag}",
                fx0,
                fx1,
                vy - 500,
                vy + 500,
                -FOOTING_H_MM,
                0,
                predefined_type="PAD_FOOTING",
            )

    total_railings = 0

    for idx, fl in enumerate(layout.floors):
        st = storeys[idx]
        t_prefix = f"T{idx + 1}"
        elev = fl.elevation_mm
        h = fl.height_mm

        # Slab
        slab_boxes: list[tuple[float, float, float, float, float, float]] = [
            (
                float(x0 - 100),
                float(x1 + 100),
                float(y0 - 100),
                float(y1 + 100),
                float(elev),
                float(elev + SLAB_MM),
            )
        ]
        for r in fl.rooms:
            if r.y_mm < y0:
                slab_boxes.append(
                    (
                        float(r.x_mm),
                        float(r.x_mm + r.w_mm),
                        float(r.y_mm),
                        float(y0 - 100),
                        float(elev),
                        float(elev + SLAB_MM),
                    )
                )
        slab = _multi_box_mm(
            model,
            body,
            st,
            "IfcSlab",
            f"{t_prefix} S01",
            slab_boxes,
            predefined_type="FLOOR",
        )
        stair_room = next((r for r in fl.rooms if r.id == "stair"), None)
        if idx > 0 and stair_room is not None:
            void = _box_mm(
                model,
                body,
                st,
                "IfcOpeningElement",
                f"{t_prefix} OS01",
                stair_room.x_mm + 100,
                stair_room.x_mm + stair_room.w_mm - 100,
                stair_room.y_mm + 100,
                stair_room.y_mm + stair_room.d_mm - 100,
                elev - 50,
                elev + SLAB_MM + 50,
                contain=False,
            )
            run("feature.add_feature", model, feature=void, element=slab)

        for r in fl.rooms:
            if r.kind != "stair" and rules[r.kind].light_well and fl.index > first_well_floor[r.id]:
                well_void = _box_mm(
                    model,
                    body,
                    st,
                    "IfcOpeningElement",
                    f"{t_prefix} OS_{r.id}",
                    r.x_mm + 100,
                    r.x_mm + r.w_mm - 100,
                    r.y_mm + 100,
                    r.y_mm + r.d_mm - 100,
                    elev - 50,
                    elev + SLAB_MM + 50,
                    contain=False,
                )
                run("feature.add_feature", model, feature=well_void, element=slab)

        # Columns at grid intersections
        for u_i, ux in enumerate(u_axes_mm):
            for v_i, vy in enumerate(v_axes_mm):
                v_tag = chr(65 + v_i)
                _box_mm(
                    model,
                    body,
                    st,
                    "IfcColumn",
                    f"{t_prefix} C{u_i + 1}-{v_tag}",
                    ux - COL_X_MM // 2,
                    ux + COL_X_MM // 2,
                    vy - COL_Y_MM // 2,
                    vy + COL_Y_MM // 2,
                    elev + SLAB_MM,
                    elev + h,
                    predefined_type="COLUMN",
                )

        # Beams along U axes between adjacent columns
        b_idx = 0
        for u_i, ux in enumerate(u_axes_mm):
            for ya, yb in zip(v_axes_mm[:-1], v_axes_mm[1:]):
                b_idx += 1
                _box_mm(
                    model,
                    body,
                    st,
                    "IfcBeam",
                    f"{t_prefix} B{b_idx:02d}",
                    ux - BEAM_W_MM // 2,
                    ux + BEAM_W_MM // 2,
                    ya + COL_Y_MM // 2,
                    yb - COL_Y_MM // 2,
                    elev + h - BEAM_H_MM,
                    elev + h,
                    predefined_type="BEAM",
                )

        # Walls, doors, windows
        _build_floor_walls_and_openings(
            model, body, st, fl, layout.buildable_mm, v_axes_mm, h, rules, t_prefix
        )

        # Railings on upper floor outdoor rooms
        if idx > 0:
            r_idx = 0
            for r in fl.rooms:
                if r.kind == "stair" or not rules[r.kind].outdoor:
                    continue
                if r.y_mm < y0:
                    rail_boxes = [
                        (
                            r.x_mm + 100,
                            r.x_mm + r.w_mm - 100,
                            r.y_mm,
                            r.y_mm + RAILING_THICK_MM,
                        ),
                        (
                            r.x_mm,
                            r.x_mm + RAILING_THICK_MM,
                            r.y_mm + 100,
                            y0 - 200,
                        ),
                        (
                            r.x_mm + r.w_mm - RAILING_THICK_MM,
                            r.x_mm + r.w_mm,
                            r.y_mm + 100,
                            y0 - 200,
                        ),
                    ]
                    for rx0_b, rx1_b, ry0_b, ry1_b in rail_boxes:
                        r_idx += 1
                        total_railings += 1
                        _box_mm(
                            model,
                            body,
                            st,
                            "IfcRailing",
                            f"{t_prefix} R{r_idx:02d}",
                            rx0_b,
                            rx1_b,
                            ry0_b,
                            ry1_b,
                            elev + SLAB_MM,
                            elev + SLAB_MM + RAILING_H_MM,
                            predefined_type="GUARDRAIL",
                        )
                else:
                    if r.y_mm == y0:
                        ry0, ry1 = y0, y0 + RAILING_THICK_MM
                    else:
                        ry0, ry1 = y1 - RAILING_THICK_MM, y1
                    r_idx += 1
                    total_railings += 1
                    _box_mm(
                        model,
                        body,
                        st,
                        "IfcRailing",
                        f"{t_prefix} R{r_idx:02d}",
                        r.x_mm + 100,
                        r.x_mm + r.w_mm - 100,
                        ry0,
                        ry1,
                        elev + SLAB_MM,
                        elev + SLAB_MM + RAILING_H_MM,
                        predefined_type="GUARDRAIL",
                    )

        # Spaces
        spaces: list[ifcopenshell.entity_instance] = []
        for r in fl.rooms:
            sp = _box_mm(
                model,
                body,
                st,
                "IfcSpace",
                r.id,
                r.x_mm,
                r.x_mm + r.w_mm,
                r.y_mm,
                r.y_mm + r.d_mm,
                elev + SLAB_MM,
                elev + h,
                contain=False,
            )
            sp.LongName = "Cầu thang" if r.kind == "stair" else rules[r.kind].label
            spaces.append(sp)
        if spaces:
            run("aggregate.assign_object", model, relating_object=st, products=spaces)

        # Stair (every floor except the top floor)
        if idx < len(layout.floors) - 1 and stair_room is not None:
            _build_stair(model, body, st, fl, stair_room, h, t_prefix)

    # Top floor roof (covers indoor rooms only)
    top_fl = layout.floors[-1]
    top_st = storeys[-1]
    top_prefix = f"T{len(layout.floors)}"
    z_roof0 = top_fl.elevation_mm + top_fl.height_mm
    z_roof1 = z_roof0 + SLAB_MM
    indoor_top = [
        r
        for r in top_fl.rooms
        if r.kind == "stair" or not (rules[r.kind].outdoor or rules[r.kind].light_well)
    ]
    if indoor_top:
        roof_boxes = [
            (
                float(r.x_mm),
                float(r.x_mm + r.w_mm),
                float(r.y_mm),
                float(r.y_mm + r.d_mm),
                float(z_roof0),
                float(z_roof1),
            )
            for r in indoor_top
        ]
    else:
        roof_boxes = [
            (
                float(x0 - 100),
                float(x1 + 100),
                float(y0 - 100),
                float(y1 + 100),
                float(z_roof0),
                float(z_roof1),
            )
        ]
    _multi_box_mm(
        model,
        body,
        top_st,
        "IfcRoof",
        f"{top_prefix} RF01",
        roof_boxes,
        predefined_type="FLAT_ROOF",
    )

    # Glass roof plates over light wells
    wells = {
        r.id: r
        for fl in layout.floors
        for r in fl.rooms
        if r.kind != "stair" and rules[r.kind].light_well
    }
    for w_i, (wid, wr) in enumerate(wells.items(), 1):
        _box_mm(
            model,
            body,
            top_st,
            "IfcPlate",
            f"{top_prefix} PL{w_i:02d}_{wid}",
            wr.x_mm + 200,
            wr.x_mm + wr.w_mm - 200,
            wr.y_mm + 200,
            wr.y_mm + wr.d_mm - 200,
            z_roof0,
            z_roof0 + 20,
            predefined_type="SHEET",
        )

    # Parapet walls on top of the roof
    if indoor_top:
        px0 = min(r.x_mm for r in indoor_top)
        px1 = max(r.x_mm + r.w_mm for r in indoor_top)
        py0 = min(r.y_mm for r in indoor_top)
        py1 = max(r.y_mm + r.d_mm for r in indoor_top)
    else:
        px0, py0, px1, py1 = x0, y0, x1, y1

    parapet_specs = [
        (f"{top_prefix} PW01", px0, px1, py0, py0 + EXT_WALL_MM),
        (f"{top_prefix} PW02", px0, px1, py1 - EXT_WALL_MM, py1),
        (f"{top_prefix} PW03", px0, px0 + EXT_WALL_MM, py0 + EXT_WALL_MM, py1 - EXT_WALL_MM),
        (f"{top_prefix} PW04", px1 - EXT_WALL_MM, px1, py0 + EXT_WALL_MM, py1 - EXT_WALL_MM),
    ]
    parapets: list[ifcopenshell.entity_instance] = []
    for p_name, bx0, bx1, by0, by1 in parapet_specs:
        if bx1 <= bx0 or by1 <= by0:
            continue
        pw = _box_mm(
            model,
            body,
            top_st,
            "IfcWall",
            p_name,
            bx0,
            bx1,
            by0,
            by1,
            z_roof1,
            z_roof1 + RAILING_H_MM,
            predefined_type="PARAPET",
        )
        pset = run("pset.add_pset", model, product=pw, name="Pset_WallCommon")
        run("pset.edit_pset", model, pset=pset, properties={"IsExternal": True})
        parapets.append(pw)

    for i in range(len(parapets)):
        other = parapets[(i + 1) % len(parapets)]
        if other != parapets[i]:
            model.create_entity(
                "IfcRelConnectsPathElements",
                GlobalId=ifcopenshell.guid.new(),
                RelatingElement=parapets[i],
                RelatedElement=other,
                RelatingConnectionType="ATEND",
                RelatedConnectionType="ATSTART",
                RelatingPriorities=[],
                RelatedPriorities=[],
            )

    if total_railings == 0:
        for r_i, (ry0, ry1) in enumerate(
            (
                (py0 + EXT_WALL_MM + 50, py0 + EXT_WALL_MM + 50 + RAILING_THICK_MM),
                (py1 - EXT_WALL_MM - 50 - RAILING_THICK_MM, py1 - EXT_WALL_MM - 50),
            ),
            1,
        ):
            _box_mm(
                model,
                body,
                top_st,
                "IfcRailing",
                f"{top_prefix} R{r_i:02d}",
                px0 + EXT_WALL_MM + 50,
                px1 - EXT_WALL_MM - 50,
                ry0,
                ry1,
                z_roof1,
                z_roof1 + RAILING_H_MM,
                predefined_type="GUARDRAIL",
            )

    assign_building_materials(model, body)
    return model
