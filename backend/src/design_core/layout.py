"""CP-SAT floor-plan layout solver for narrow urban houses (nhà phố)."""

from __future__ import annotations

import math
import time
from typing import Any

from ortools.sat.python import cp_model
from pydantic import BaseModel

from src.design_core.program import Program
from src.design_core.typologies import balcony_projection_m, load_rules

GRID_MM = 100


class LayoutInfeasible(ValueError):
    """Raised when a Program cannot be realized into a valid floor-plan layout."""


class PlacedRoom(BaseModel):
    id: str
    kind: str
    x_mm: int
    y_mm: int
    w_mm: int
    d_mm: int


class Connection(BaseModel):
    a: str
    b: str
    x0_mm: int
    y0_mm: int
    x1_mm: int
    y1_mm: int


class FloorLayout(BaseModel):
    name: str
    index: int
    elevation_mm: int
    height_mm: int
    rooms: list[PlacedRoom]
    connections: list[Connection]


class SolveStats(BaseModel):
    status: str
    objective: float
    wall_time_s: float


class Layout(BaseModel):
    program_name: str
    typology: str
    buildable_mm: tuple[int, int, int, int]
    floors: list[FloorLayout]
    stats: SolveStats


def _shared_segment_mm(a: PlacedRoom, b: PlacedRoom) -> tuple[int, int, int, int] | None:
    """Compute full shared boundary segment (x0, y0, x1, y1) in mm between two placed rooms."""
    ax, ay, aw, ad = a.x_mm, a.y_mm, a.w_mm, a.d_mm
    bx, by, bw, bd = b.x_mm, b.y_mm, b.w_mm, b.d_mm
    for xa, xb in ((ax + aw, bx), (bx + bw, ax)):
        if xa == xb:
            lo, hi = max(ay, by), min(ay + ad, by + bd)
            if hi > lo:
                return (xa, lo, xa, hi)
    for ya, yb in ((ay + ad, by), (by + bd, ay)):
        if ya == yb:
            lo, hi = max(ax, bx), min(ax + aw, bx + bw)
            if hi > lo:
                return (lo, ya, hi, ya)
    return None


def solve_layout(program: Program, max_deterministic_time: float = 10.0) -> Layout:
    """Solve all floors of `program` simultaneously using OR-Tools CP-SAT on a 100 mm grid."""
    rules = load_rules(program.typology)
    lot = program.lot

    x0_g = 0
    y0_g = round(lot.front_setback_m * 10)
    x1_g = round(lot.width_m * 10)
    y1_g = round((lot.depth_m - lot.back_setback_m) * 10)

    w_build_g = x1_g - x0_g
    d_build_g = y1_g - y0_g
    if w_build_g <= 0 or d_build_g <= 0:
        raise LayoutInfeasible("Phạm vi xây dựng có diện tích không dương")

    build_area_g = w_build_g * d_build_g
    build_area_m2 = build_area_g / 100.0
    buildable_mm = (x0_g * GRID_MM, y0_g * GRID_MM, x1_g * GRID_MM, y1_g * GRID_MM)

    stair_area_m2 = (program.stair.width_m * program.stair.length_m) if program.stair else 0.0
    stair_w_g = round(program.stair.width_m * 10) if program.stair else 0
    stair_d_g = round(program.stair.length_m * 10) if program.stair else 0
    stair_area_g = stair_w_g * stair_d_g
    proj_g = round(balcony_projection_m(program.typology, lot.street_width_m) * 10)

    for floor in program.floors:
        non_proj = [r for r in floor.rooms if not r.projecting]
        min_sum_m2 = sum(float(r.min_area_m2 or 0.0) for r in non_proj) + stair_area_m2
        min_sum_g = (
            sum(math.ceil(float(r.min_area_m2 or 0.0) * 100 - 1e-9) for r in non_proj)
            + stair_area_g
        )
        if min_sum_m2 > build_area_m2 + 1e-9 or min_sum_g > build_area_g:
            raise LayoutInfeasible(
                f"{floor.name}: tổng diện tích tối thiểu {min_sum_m2:.1f} m² "
                f"vượt diện tích xây dựng {build_area_m2:.1f} m²"
            )

    if program.stair is not None and (stair_w_g > w_build_g or stair_d_g > d_build_g):
        raise LayoutInfeasible("Cầu thang vượt quá kích thước phạm vi xây dựng")

    model = cp_model.CpModel()
    min_shared_g = math.ceil(program.min_shared_m * 10 - 1e-9)

    stair_vars: dict[str, Any] | None = None
    if program.stair is not None:
        sx = model.new_int_var(x0_g, x1_g - stair_w_g, "stair_x")
        sy = model.new_int_var(y0_g, y1_g - stair_d_g, "stair_y")
        sw = model.new_constant(stair_w_g)
        sd = model.new_constant(stair_d_g)
        sx_end = model.new_int_var(x0_g + stair_w_g, x1_g, "stair_x_end")
        sy_end = model.new_int_var(y0_g + stair_d_g, y1_g, "stair_y_end")
        model.add(sx_end == sx + stair_w_g)
        model.add(sy_end == sy + stair_d_g)
        sx_iv = model.new_fixed_size_interval_var(sx, stair_w_g, "stair_x_iv")
        sy_iv = model.new_fixed_size_interval_var(sy, stair_d_g, "stair_y_iv")
        stair_vars = {
            "x": sx,
            "y": sy,
            "w": sw,
            "d": sd,
            "x_end": sx_end,
            "y_end": sy_end,
            "x_iv": sx_iv,
            "y_iv": sy_iv,
        }

    light_well_vars: dict[str, dict[str, Any]] = {}
    floor_room_vars: list[dict[str, dict[str, Any]]] = []
    floor_pairs: list[list[tuple[str, str]]] = []
    abs_diffs: list[cp_model.IntVar] = []

    for f_idx, floor in enumerate(program.floors):
        r_vars: dict[str, dict[str, Any]] = {}
        x_ivs: list[cp_model.IntervalVar] = []
        y_ivs: list[cp_model.IntervalVar] = []
        area_vars: list[cp_model.IntVar] = []

        ids = [r.id for r in floor.rooms] + (["stair"] if program.stair else [])
        neigh: dict[str, set[str]] = {rid: set() for rid in ids}
        pairs_set: set[tuple[str, str]] = set()
        for req in floor.rooms:
            for other in req.adjacent_to:
                neigh[req.id].add(other)
                neigh[other].add(req.id)
                a, b = sorted((req.id, other))
                pairs_set.add((a, b))
        sorted_pairs = sorted(pairs_set)
        floor_pairs.append(sorted_pairs)
        kind_of = {req.id: req.kind for req in floor.rooms}

        min_sum_g = (
            sum(
                math.ceil(float(r.min_area_m2 or 0.0) * 100 - 1e-9)
                for r in floor.rooms
                if not r.projecting
            )
            + stair_area_g
        )

        for req in floor.rooms:
            rid = req.id
            prefix = f"f{f_idx}_{rid}"
            min_w_g = math.ceil(float(req.min_width_m or 0.0) * 10 - 1e-9)
            min_area_g = math.ceil(float(req.min_area_m2 or 0.0) * 100 - 1e-9)
            aspect_scaled = round(100 * float(req.max_aspect or 1.0))

            if req.projecting:
                if proj_g <= 0 or min_w_g <= 0 or min_w_g > w_build_g or min_w_g > proj_g:
                    raise LayoutInfeasible(
                        f"{floor.name}/{rid}: kích thước tối thiểu của ban công đua vượt quá phạm vi cho phép"
                    )
                w_lb = max(min_w_g, (min_area_g + proj_g - 1) // proj_g)
                w_ub = w_build_g
                max_area_g = w_ub * proj_g
                if w_lb > w_ub or min_area_g > max_area_g:
                    raise LayoutInfeasible(
                        f"{floor.name}/{rid}: miền kích thước ban công đua rỗng"
                    )

                x = model.new_int_var(x0_g, x1_g - w_lb, f"{prefix}_x")
                y = model.new_constant(y0_g - proj_g)
                w = model.new_int_var(w_lb, w_ub, f"{prefix}_w")
                d = model.new_constant(proj_g)
                x_end = model.new_int_var(x0_g + w_lb, x1_g, f"{prefix}_x_end")
                y_end = model.new_constant(y0_g)
                model.add(x_end == x + w)

                x_iv = model.new_interval_var(x, w, x_end, f"{prefix}_x_iv")
                y_iv = model.new_fixed_size_interval_var(y, proj_g, f"{prefix}_y_iv")

                area = model.new_int_var(min_area_g, max_area_g, f"{prefix}_area")
                model.add_multiplication_equality(area, [w, d])

                model.add(100 * w <= aspect_scaled * d)
                model.add(100 * d <= aspect_scaled * w)

                target_g = round(float(req.target_area_m2 or req.min_area_m2 or 0.0) * 100)
                abs_diff = model.new_int_var(
                    0, max(build_area_g, max_area_g, target_g), f"{prefix}_abs_diff"
                )
                model.add_abs_equality(abs_diff, area - target_g)
                abs_diffs.append(abs_diff)

                r_vars[rid] = {
                    "x": x,
                    "y": y,
                    "w": w,
                    "d": d,
                    "x_end": x_end,
                    "y_end": y_end,
                }
                x_ivs.append(x_iv)
                y_ivs.append(y_iv)
                continue

            max_area_g = build_area_g - (min_sum_g - min_area_g)

            if min_w_g <= 0 or min_w_g > w_build_g or min_w_g > d_build_g or min_area_g > max_area_g:
                raise LayoutInfeasible(
                    f"{floor.name}/{rid}: kích thước tối thiểu vượt quá phạm vi xây dựng"
                )

            w_lb = max(min_w_g, (min_area_g + d_build_g - 1) // d_build_g)
            d_lb = max(min_w_g, (min_area_g + w_build_g - 1) // w_build_g)
            w_ub = min(w_build_g, max_area_g // min_w_g)
            d_ub = min(d_build_g, max_area_g // min_w_g)

            if w_lb > w_ub or d_lb > d_ub:
                raise LayoutInfeasible(
                    f"{floor.name}/{rid}: miền kích thước rỗng trong phạm vi xây dựng"
                )

            is_light_well = rules[req.kind].light_well
            if is_light_well and rid in light_well_vars:
                lw = light_well_vars[rid]
                x = lw["x"]
                y = lw["y"]
                w = lw["w"]
                d = lw["d"]
                x_end = lw["x_end"]
                y_end = lw["y_end"]
                x_iv = lw["x_iv"]
                y_iv = lw["y_iv"]
                area = lw["area"]
                model.add(w >= w_lb)
                model.add(w <= w_ub)
                model.add(d >= d_lb)
                model.add(d <= d_ub)
                model.add(area >= min_area_g)
                model.add(area <= max_area_g)
            else:
                x = model.new_int_var(x0_g, x1_g - w_lb, f"{prefix}_x")
                y = model.new_int_var(y0_g, y1_g - d_lb, f"{prefix}_y")
                w = model.new_int_var(w_lb, w_ub, f"{prefix}_w")
                d = model.new_int_var(d_lb, d_ub, f"{prefix}_d")
                x_end = model.new_int_var(x0_g + w_lb, x1_g, f"{prefix}_x_end")
                y_end = model.new_int_var(y0_g + d_lb, y1_g, f"{prefix}_y_end")
                model.add(x_end == x + w)
                model.add(y_end == y + d)

                x_iv = model.new_interval_var(x, w, x_end, f"{prefix}_x_iv")
                y_iv = model.new_interval_var(y, d, y_end, f"{prefix}_y_iv")

                area = model.new_int_var(min_area_g, max_area_g, f"{prefix}_area")
                model.add_multiplication_equality(area, [w, d])

                if is_light_well:
                    light_well_vars[rid] = {
                        "x": x,
                        "y": y,
                        "w": w,
                        "d": d,
                        "x_end": x_end,
                        "y_end": y_end,
                        "x_iv": x_iv,
                        "y_iv": y_iv,
                        "area": area,
                    }

            model.add(100 * w <= aspect_scaled * d)
            model.add(100 * d <= aspect_scaled * w)

            outdoor = rules[req.kind].outdoor
            if req.entrance:
                model.add(y == y0_g)
            elif outdoor:
                tf = model.new_bool_var(f"{prefix}_front")
                tb = model.new_bool_var(f"{prefix}_back")
                model.add(y == y0_g).only_enforce_if(tf)
                model.add(y_end == y1_g).only_enforce_if(tb)
                model.add_bool_or([tf, tb])
            elif req.needs_daylight:
                lit_by_outdoor = any(
                    n != "stair" and (rules[kind_of[n]].outdoor or rules[kind_of[n]].light_well)
                    for n in neigh[rid]
                )
                if not lit_by_outdoor:
                    tf = model.new_bool_var(f"{prefix}_daylight_front")
                    tb = model.new_bool_var(f"{prefix}_daylight_back")
                    model.add(y == y0_g).only_enforce_if(tf)
                    model.add(y_end == y1_g).only_enforce_if(tb)
                    model.add_bool_or([tf, tb])

            target_g = round(float(req.target_area_m2 or req.min_area_m2 or 0.0) * 100)
            abs_diff = model.new_int_var(0, build_area_g, f"{prefix}_abs_diff")
            model.add_abs_equality(abs_diff, area - target_g)
            abs_diffs.append(abs_diff)

            r_vars[rid] = {
                "x": x,
                "y": y,
                "w": w,
                "d": d,
                "x_end": x_end,
                "y_end": y_end,
            }
            x_ivs.append(x_iv)
            y_ivs.append(y_iv)
            area_vars.append(area)

        if stair_vars is not None:
            r_vars["stair"] = stair_vars
            x_ivs.append(stair_vars["x_iv"])
            y_ivs.append(stair_vars["y_iv"])

        model.add_no_overlap_2d(x_ivs, y_ivs)
        model.add(sum(area_vars) + stair_area_g == build_area_g)

        for a_id, b_id in sorted_pairs:
            va = r_vars[a_id]
            vb = r_vars[b_id]
            p_prefix = f"f{f_idx}_adj_{a_id}_{b_id}"

            c_right = model.new_bool_var(f"{p_prefix}_right")
            model.add(va["x_end"] == vb["x"]).only_enforce_if(c_right)
            model.add(vb["y"] <= va["y_end"] - min_shared_g).only_enforce_if(c_right)
            model.add(va["y"] <= vb["y_end"] - min_shared_g).only_enforce_if(c_right)

            c_left = model.new_bool_var(f"{p_prefix}_left")
            model.add(vb["x_end"] == va["x"]).only_enforce_if(c_left)
            model.add(vb["y"] <= va["y_end"] - min_shared_g).only_enforce_if(c_left)
            model.add(va["y"] <= vb["y_end"] - min_shared_g).only_enforce_if(c_left)

            c_back = model.new_bool_var(f"{p_prefix}_back")
            model.add(va["y_end"] == vb["y"]).only_enforce_if(c_back)
            model.add(vb["x"] <= va["x_end"] - min_shared_g).only_enforce_if(c_back)
            model.add(va["x"] <= vb["x_end"] - min_shared_g).only_enforce_if(c_back)

            c_front = model.new_bool_var(f"{p_prefix}_front")
            model.add(vb["y_end"] == va["y"]).only_enforce_if(c_front)
            model.add(vb["x"] <= va["x_end"] - min_shared_g).only_enforce_if(c_front)
            model.add(va["x"] <= vb["x_end"] - min_shared_g).only_enforce_if(c_front)

            model.add_bool_or([c_right, c_left, c_back, c_front])

        floor_room_vars.append(r_vars)

    model.minimize(sum(abs_diffs))

    solver = cp_model.CpSolver()
    solver.parameters.num_workers = 8
    solver.parameters.interleave_search = True
    solver.parameters.random_seed = 0
    solver.parameters.max_deterministic_time = float(max_deterministic_time)

    t0 = time.perf_counter()
    status = solver.solve(model)
    wall_time_s = time.perf_counter() - t0
    status_name = solver.status_name(status)

    if status in (cp_model.INFEASIBLE, cp_model.MODEL_INVALID):
        raise LayoutInfeasible(
            f"Không xếp được mặt bằng thỏa mọi ràng buộc cho '{program.name}' (status={status_name})"
        )
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise LayoutInfeasible(
            f"Hết thời gian giải mà chưa tìm được mặt bằng cho '{program.name}' (status={status_name})"
        )

    floors_out: list[FloorLayout] = []
    elev_mm = 0

    for f_idx, floor in enumerate(program.floors):
        h_mm = round(float(floor.height_m or 3.6) * 1000)
        r_vars = floor_room_vars[f_idx]
        placed_rooms: list[PlacedRoom] = []
        placed_by_id: dict[str, PlacedRoom] = {}

        for req in floor.rooms:
            v = r_vars[req.id]
            pr = PlacedRoom(
                id=req.id,
                kind=req.kind,
                x_mm=int(solver.value(v["x"])) * GRID_MM,
                y_mm=int(solver.value(v["y"])) * GRID_MM,
                w_mm=int(solver.value(v["w"])) * GRID_MM,
                d_mm=int(solver.value(v["d"])) * GRID_MM,
            )
            placed_rooms.append(pr)
            placed_by_id[req.id] = pr

        if program.stair is not None and stair_vars is not None:
            pr_stair = PlacedRoom(
                id="stair",
                kind="stair",
                x_mm=int(solver.value(stair_vars["x"])) * GRID_MM,
                y_mm=int(solver.value(stair_vars["y"])) * GRID_MM,
                w_mm=stair_w_g * GRID_MM,
                d_mm=stair_d_g * GRID_MM,
            )
            placed_rooms.append(pr_stair)
            placed_by_id["stair"] = pr_stair

        connections_out: list[Connection] = []
        for a_id, b_id in floor_pairs[f_idx]:
            seg = _shared_segment_mm(placed_by_id[a_id], placed_by_id[b_id])
            if seg is None:
                raise LayoutInfeasible(f"Không tìm thấy đoạn cạnh chung giữa {a_id} và {b_id}")
            connections_out.append(
                Connection(
                    a=a_id,
                    b=b_id,
                    x0_mm=seg[0],
                    y0_mm=seg[1],
                    x1_mm=seg[2],
                    y1_mm=seg[3],
                )
            )

        floors_out.append(
            FloorLayout(
                name=floor.name,
                index=f_idx,
                elevation_mm=elev_mm,
                height_mm=h_mm,
                rooms=placed_rooms,
                connections=connections_out,
            )
        )
        elev_mm += h_mm

    return Layout(
        program_name=program.name,
        typology=program.typology,
        buildable_mm=buildable_mm,
        floors=floors_out,
        stats=SolveStats(
            status=status_name,
            objective=float(solver.objective_value),
            wall_time_s=wall_time_s,
        ),
    )
