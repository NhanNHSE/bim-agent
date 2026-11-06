"""Acceptance tests: identical floor programs ("tầng điển hình") get identical layouts. LOCKED.

Town houses stack their typical floors: walls, wet rooms and shafts line up vertically, which is what an
engineer expects for structure and plumbing. It also halves the CP-SAT search: on GitHub's CI runner the
5x20 sample took 11.9 s with every floor solved independently (limit 10 s, test_layout_quality_accept.py).

Two floors are "identical" when their room lists are equal after defaults are filled in (ids, kinds,
sizes, targets, flags, adjacency); storey height and floor name may differ.
"""

import copy

from src.design_core.layout import solve_layout
from src.design_core.program import Program
from src.design_core.typologies import load_samples

SAMPLE = next(p for p in load_samples("nha_pho") if p.name.startswith("nha_pho_5x20"))


def _rects(fl):
    return [(r.id, r.x_mm, r.y_mm, r.w_mm, r.d_mm) for r in fl.rooms]


def test_identical_typical_floors_share_one_layout():
    t2, t3 = SAMPLE.floors[1], SAMPLE.floors[2]
    assert [r.model_dump() for r in t2.rooms] == [r.model_dump() for r in t3.rooms]  # precondition (locked data)
    lay = solve_layout(SAMPLE)
    assert _rects(lay.floors[1]) == _rects(lay.floors[2])
    assert lay.floors[1].height_mm != lay.floors[2].height_mm  # heights may differ, plans must not


def test_5x20_sample_proves_optimality_within_a_small_deterministic_budget():
    """Machine-independent speed bar. Before this task: FEASIBLE at 3.0 (needed ~10) -> 11.9 s wall on CI."""
    lay = solve_layout(SAMPLE, max_deterministic_time=3.0)
    assert lay.stats.status == "OPTIMAL"


def test_floors_that_differ_are_solved_independently():
    d = SAMPLE.model_dump(exclude_none=True)
    d = copy.deepcopy(d)
    d["name"] = "khac_nhau"
    for r in d["floors"][2]["rooms"]:  # make floor 3 different: front bedroom must be >= 24 m2
        if r["id"] == "ngu1":  # feasible, e.g. ngu1 0 0 5x5, wc1 2.2 5 2.8x2.6, kho 2.2 7.6 2.8x1.9, sanh 0 5 2.2x4.5
            r["min_area_m2"] = 24.0
            r["target_area_m2"] = 25.0
    prog = Program.model_validate(d)
    lay = solve_layout(prog)
    assert lay.stats.status in {"OPTIMAL", "FEASIBLE"}
    a = {r.id: r.w_mm * r.d_mm for r in lay.floors[2].rooms}
    b = {r.id: r.w_mm * r.d_mm for r in lay.floors[1].rooms}
    assert a["ngu1"] >= 24_000_000 > b["ngu1"]
