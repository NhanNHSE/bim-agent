"""Regression tests: the layout objective is a true |area - target| sum. LOCKED.

ortools 9.12.4544 builds `add_abs_equality(t, expr)` wrongly when `expr` has a constant offset:
the negated branch keeps the offset's sign (|x - 5| becomes max(x - 5, -x - 5)), so every room was
silently forced to area >= target. Programs whose targets add up to more than the floor were reported
infeasible, and the objective was not the real deviation. Claude reproduced it on 9.12 (fine on 9.14);
we stay on 9.12 for the patched protobuf, so the solver must not rely on abs-of-offset expressions.
"""

import copy

import pytest

from src.design_core.layout import solve_layout
from src.design_core.program import Program
from src.design_core.typologies import load_samples
from tests.unit.test_layout_accept import layout_violations
from src.design_core.typologies import load_rules

RULES = load_rules("nha_pho")
BASE = next(p for p in load_samples("nha_pho") if p.name == "nha_pho_4x16_3t")


def _scaled(factor: float) -> Program:
    d = copy.deepcopy(BASE.model_dump(exclude_none=True))
    d["name"] = f"scaled_{factor}"
    for fl in d["floors"]:
        for r in fl["rooms"]:
            r["target_area_m2"] = round(r["target_area_m2"] * factor, 2)
    return Program.model_validate(d)


def _deviation_cells(prog: Program, lay) -> int:
    total = 0
    for fp, fl in zip(prog.floors, lay.floors):
        placed = {r.id: r for r in fl.rooms}
        for req in fp.rooms:
            r = placed[req.id]
            total += abs((r.w_mm // 100) * (r.d_mm // 100) - round(req.target_area_m2 * 100))
    return total


@pytest.mark.parametrize("factor", [1.15, 0.85])
def test_targets_that_do_not_add_up_still_solve(factor):
    prog = _scaled(factor)
    lay = solve_layout(prog)
    assert lay.stats.status in {"OPTIMAL", "FEASIBLE"}
    assert layout_violations(prog, lay.model_dump(), RULES) == []


@pytest.mark.parametrize("factor", [1.15, 0.85])
def test_objective_is_the_real_absolute_deviation(factor):
    prog = _scaled(factor)
    lay = solve_layout(prog)
    assert lay.stats.objective == pytest.approx(_deviation_cells(prog, lay), abs=1)
    assert lay.stats.objective > 0  # targets cannot all be met exactly when they over/under-fill the floor


def test_some_room_may_end_up_smaller_than_its_target():
    prog = _scaled(1.15)
    lay = solve_layout(prog)
    smaller = [
        req.id
        for fp, fl in zip(prog.floors, lay.floors)
        for req in fp.rooms
        for r in fl.rooms
        if r.id == req.id and r.w_mm * r.d_mm < req.target_area_m2 * 1e6 - 1
    ]
    assert smaller, "với mục tiêu vượt diện tích sàn, phải có phòng nhỏ hơn mục tiêu"
