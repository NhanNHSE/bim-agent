"""Automatic IFC4 model checks for geometry, topology, and schema quality."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.util.placement
import ifcopenshell.util.unit
import ifcopenshell.validate
import numpy as np

LOD200_REQUIRED: list[str] = [
    "IfcFooting",
    "IfcColumn",
    "IfcBeam",
    "IfcSlab",
    "IfcWall",
    "IfcDoor",
    "IfcWindow",
    "IfcStair",
    "IfcRailing",
    "IfcRoof",
    "IfcSpace",
]


@dataclass(frozen=True)
class Issue:
    check: str
    message: str
    element: str | None
    other: str | None = None


def _label(entity: ifcopenshell.entity_instance) -> str:
    name = getattr(entity, "Name", None)
    guid = getattr(entity, "GlobalId", None)
    ident = name or guid or f"#{entity.id()}"
    return f"{entity.is_a()} {ident}"


def check_schema(model: ifcopenshell.file) -> list[Issue]:
    logger = ifcopenshell.validate.json_logger()
    ifcopenshell.validate.validate(model, logger)
    issues: list[Issue] = []
    for stmt in logger.statements:
        inst = stmt.get("instance")
        guid = getattr(inst, "GlobalId", None) if inst is not None else None
        msg_raw = stmt.get("message", "Lỗi schema IFC")
        if inst is not None and hasattr(inst, "is_a"):
            msg = f"Lỗi schema trên {_label(inst)}: {msg_raw}"
        else:
            msg = f"Lỗi schema IFC: {msg_raw}"
        issues.append(Issue(check="schema", message=msg, element=guid))
    return issues


def check_required_classes(
    model: ifcopenshell.file,
    required: list[str] = LOD200_REQUIRED,
) -> list[Issue]:
    issues: list[Issue] = []
    for cls in required:
        if not model.by_type(cls):
            issues.append(
                Issue(
                    check="required_classes",
                    message=f"Model thiếu lớp IFC bắt buộc: {cls}",
                    element=None,
                )
            )
    return issues


def _host_walls(element: ifcopenshell.entity_instance) -> set[int]:
    """Return IDs of IfcWall entities that host `element` via IfcRelFillsElement -> IfcOpeningElement -> IfcRelVoidsElement."""
    wall_ids: set[int] = set()
    for rel_fills in getattr(element, "FillsVoids", ()) or ():
        opening = getattr(rel_fills, "RelatingOpeningElement", None)
        if opening is None:
            continue
        voids = getattr(opening, "VoidsElements", ()) or ()
        if not isinstance(voids, (tuple, list)):
            voids = (voids,)
        for rel_voids in voids:
            host = getattr(rel_voids, "RelatingBuildingElement", None)
            if host is not None and host.is_a("IfcWall"):
                wall_ids.add(host.id())
    return wall_ids


def check_openings(model: ifcopenshell.file) -> list[Issue]:
    issues: list[Issue] = []
    for cls in ("IfcDoor", "IfcWindow"):
        for el in model.by_type(cls):
            if not _host_walls(el):
                issues.append(
                    Issue(
                        check="openings",
                        message=f"{_label(el)} không gắn vào lỗ mở (IfcOpeningElement) thuộc tường (IfcWall)",
                        element=el.GlobalId,
                    )
                )
    return issues


def check_wall_connections(model: ifcopenshell.file) -> list[Issue]:
    walls = model.by_type("IfcWall")
    if len(walls) < 2:
        return []
    connected_ids: set[int] = set()
    for rel in model.by_type("IfcRelConnectsPathElements"):
        if rel.RelatingElement is not None:
            connected_ids.add(rel.RelatingElement.id())
        if rel.RelatedElement is not None:
            connected_ids.add(rel.RelatedElement.id())
    issues: list[Issue] = []
    for w in walls:
        if w.id() not in connected_ids:
            issues.append(
                Issue(
                    check="wall_connections",
                    message=f"{_label(w)} chưa được kết nối bằng IfcRelConnectsPathElements",
                    element=w.GlobalId,
                )
            )
    return issues


def _line_intersection_2d(
    p1: tuple[float, float],
    p2: tuple[float, float],
    p3: tuple[float, float],
    p4: tuple[float, float],
) -> tuple[float, float] | None:
    dx_u = p2[0] - p1[0]
    dy_u = p2[1] - p1[1]
    dx_v = p4[0] - p3[0]
    dy_v = p4[1] - p3[1]
    cross = dx_u * dy_v - dy_u * dx_v
    if abs(cross) < 1e-12:
        return None
    t = ((p3[0] - p1[0]) * dy_v - (p3[1] - p1[1]) * dx_v) / cross
    return (p1[0] + t * dx_u, p1[1] + t * dy_u)


def _axis_points_2d(axis: ifcopenshell.entity_instance) -> tuple[tuple[float, float], tuple[float, float]] | None:
    curve = getattr(axis, "AxisCurve", None)
    if curve is None or not curve.is_a("IfcPolyline"):
        return None
    pts = getattr(curve, "Points", ()) or ()
    if len(pts) < 2:
        return None
    c0 = pts[0].Coordinates
    c1 = pts[1].Coordinates
    return ((float(c0[0]), float(c0[1])), (float(c1[0]), float(c1[1])))


def check_columns_on_grid(
    model: ifcopenshell.file,
    tolerance_mm: float = 10.0,
) -> list[Issue]:
    columns = model.by_type("IfcColumn")
    if not columns:
        return []
    grids = model.by_type("IfcGrid")
    if not grids:
        return [
            Issue(
                check="columns_on_grid",
                message="Model có IfcColumn nhưng không có lưới trục IfcGrid",
                element=None,
            )
        ]

    unit_scale = ifcopenshell.util.unit.calculate_unit_scale(model)
    intersections: list[np.ndarray] = []
    for grid in grids:
        g_mat = ifcopenshell.util.placement.get_local_placement(grid.ObjectPlacement)
        u_axes = [
            pts
            for ax in (getattr(grid, "UAxes", ()) or ())
            if (pts := _axis_points_2d(ax)) is not None
        ]
        v_axes = [
            pts
            for ax in (getattr(grid, "VAxes", ()) or ())
            if (pts := _axis_points_2d(ax)) is not None
        ]
        for u0, u1 in u_axes:
            for v0, v1 in v_axes:
                pt = _line_intersection_2d(u0, u1, v0, v1)
                if pt is not None:
                    abs_pt = g_mat @ np.array([pt[0], pt[1], 0.0, 1.0])
                    intersections.append(abs_pt[:2])

    issues: list[Issue] = []
    for col in columns:
        col_mat = ifcopenshell.util.placement.get_local_placement(col.ObjectPlacement)
        col_xy = col_mat[:2, 3]
        if not intersections:
            dist_mm = float("inf")
        else:
            min_dist_proj = min(float(np.hypot(col_xy[0] - pt[0], col_xy[1] - pt[1])) for pt in intersections)
            dist_mm = min_dist_proj * unit_scale * 1000.0
        if dist_mm > tolerance_mm:
            issues.append(
                Issue(
                    check="columns_on_grid",
                    message=f"{_label(col)} lệch giao điểm IfcGrid {dist_mm:.1f} mm (> {tolerance_mm:.1f} mm)",
                    element=col.GlobalId,
                )
            )
    return issues


def check_spaces(model: ifcopenshell.file) -> list[Issue]:
    issues: list[Issue] = []
    for storey in model.by_type("IfcBuildingStorey"):
        has_space = False
        for rel in getattr(storey, "IsDecomposedBy", ()) or ():
            for obj in getattr(rel, "RelatedObjects", ()) or ():
                if obj.is_a("IfcSpace"):
                    has_space = True
                    break
            if has_space:
                break
        if not has_space:
            issues.append(
                Issue(
                    check="spaces",
                    message=f"{_label(storey)} không có IfcSpace trong quan hệ IsDecomposedBy",
                    element=storey.GlobalId,
                )
            )
    return issues


def check_extent(
    model: ifcopenshell.file,
    max_m: float = 1000.0,
) -> list[Issue]:
    unit_scale = ifcopenshell.util.unit.calculate_unit_scale(model)
    issues: list[Issue] = []
    for prod in model.by_type("IfcProduct"):
        placement = getattr(prod, "ObjectPlacement", None)
        if placement is None:
            continue
        mat = ifcopenshell.util.placement.get_local_placement(placement)
        xyz_m = np.abs(mat[:3, 3]) * unit_scale
        if bool(np.any(xyz_m > max_m)):
            issues.append(
                Issue(
                    check="extent",
                    message=f"{_label(prod)} có vị trí vượt quá phạm vi {max_m} m",
                    element=prod.GlobalId,
                )
            )
    return issues


def check_clashes(
    model: ifcopenshell.file,
    tolerance_m: float = 0.002,
) -> list[Issue]:
    elements = [
        el
        for el in model.by_type("IfcElement")
        if getattr(el, "Representation", None) is not None and not el.is_a("IfcFeatureElement")
    ]
    if len(elements) < 2:
        return []

    host_wall_map: dict[int, set[int]] = {}
    for cls in ("IfcDoor", "IfcWindow"):
        for el in model.by_type(cls):
            walls = _host_walls(el)
            if walls:
                host_wall_map[el.id()] = walls

    connected_wall_pairs: set[frozenset[int]] = set()
    for rel in model.by_type("IfcRelConnectsPathElements"):
        a = getattr(rel, "RelatingElement", None)
        b = getattr(rel, "RelatedElement", None)
        if a is not None and b is not None and a.is_a("IfcWall") and b.is_a("IfcWall"):
            connected_wall_pairs.add(frozenset((a.id(), b.id())))

    it = ifcopenshell.geom.iterator(ifcopenshell.geom.settings(), model, include=elements)
    tree = ifcopenshell.geom.tree()
    if it.initialize():
        while True:
            tree.add_element(it.get())
            if not it.next():
                break
    raw_clashes = tree.clash_intersection_many(
        elements, elements, tolerance=tolerance_m, check_all=True
    )

    seen_pairs: set[frozenset[int]] = set()
    issues_by_pair: list[tuple[str, str, Issue]] = []
    for c in raw_clashes:
        id_a = c.a.id()
        id_b = c.b.id()
        if id_a == id_b:
            continue
        pair_ids = frozenset((id_a, id_b))
        if pair_ids in seen_pairs:
            continue
        if id_b in host_wall_map.get(id_a, set()) or id_a in host_wall_map.get(id_b, set()):
            continue
        if pair_ids in connected_wall_pairs:
            continue
        seen_pairs.add(pair_ids)

        el_a = model.by_id(id_a)
        el_b = model.by_id(id_b)
        if el_a.GlobalId > el_b.GlobalId:
            el_a, el_b = el_b, el_a
        issue = Issue(
            check="clashes",
            message=f"Va chạm giữa {_label(el_a)} và {_label(el_b)}",
            element=el_a.GlobalId,
            other=el_b.GlobalId,
        )
        issues_by_pair.append((el_a.GlobalId, el_b.GlobalId, issue))

    issues_by_pair.sort(key=lambda item: (item[0], item[1]))
    return [item[2] for item in issues_by_pair]


CHECKS: dict[str, Callable[[ifcopenshell.file], list[Issue]]] = {
    "schema": check_schema,
    "required_classes": check_required_classes,
    "openings": check_openings,
    "wall_connections": check_wall_connections,
    "columns_on_grid": check_columns_on_grid,
    "spaces": check_spaces,
    "extent": check_extent,
    "clashes": check_clashes,
}


def run_all(model: ifcopenshell.file) -> dict[str, list[Issue]]:
    return {name: fn(model) for name, fn in CHECKS.items()}
