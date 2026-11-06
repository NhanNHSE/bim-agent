"""Acceptance tests for task 022 (program v2: per-floor storey heights, street width + projecting balconies,
light wells, new room kinds). LOCKED.

The geometric checker is `layout_violations` from test_layout_accept.py (also locked); it now knows about
per-floor heights, projecting balconies and light wells.
"""

import copy

import pytest
from pydantic import ValidationError

from src.design_core.building import build_ifc
from src.design_core.layout import solve_layout
from src.design_core.program import Program
from src.design_core.typologies import balcony_projection_m, load_rules, load_typology
from tests.unit.test_layout_accept import layout_violations

RULES = load_rules("nha_pho")


def _v2() -> dict:
    """5 x 18 m lot on a 12 m street, 3 floors, projecting balconies, one light well through all floors.

    Feasible by construction (hand witness, metres, x y w d):
      T1: de_xe 0 0 5 5 | khach 0 5 5 4 | wc 2.2 9 2.8 2 | gieng 2.2 11 2.8 2 | bep_an 0 13 5 5 | stair 0 9 2.2 4
      T2/T3: ban_cong 0 -1.2 5 1.2 | ngu1 0 0 5 4.5 | sanh 0 4.5 5 4.5 | wc 2.2 9 2.8 2 | gieng 2.2 11 2.8 2
             | ngu2 0 13 5 5 | stair 0 9 2.2 4
    """
    upper = [
        {"id": "ban_cong", "kind": "ban_cong", "projecting": True, "adjacent_to": ["ngu1"]},
        {"id": "ngu1", "kind": "ngu", "adjacent_to": ["sanh"]},
        {"id": "sanh", "kind": "sanh", "adjacent_to": ["stair"]},
        {"id": "wc", "kind": "wc", "adjacent_to": ["sanh"]},
        {"id": "gieng", "kind": "gieng_troi", "adjacent_to": ["ngu2"]},
        {"id": "ngu2", "kind": "ngu", "adjacent_to": ["stair"]},
    ]
    return {
        "typology": "nha_pho", "name": "v2", "lot": {"width_m": 5.0, "depth_m": 18.0, "street_width_m": 12.0},
        "stair": {"width_m": 2.2, "length_m": 4.0},
        "floors": [
            {"name": "Tầng 1", "rooms": [
                {"id": "de_xe", "kind": "de_xe", "entrance": True, "adjacent_to": ["khach"]},
                {"id": "khach", "kind": "khach", "needs_daylight": False, "adjacent_to": ["stair", "wc"]},
                {"id": "wc", "kind": "wc"},
                {"id": "gieng", "kind": "gieng_troi", "adjacent_to": ["bep_an"]},
                {"id": "bep_an", "kind": "bep_an", "adjacent_to": ["stair"]},
            ]},
            {"name": "Tầng 2", "rooms": copy.deepcopy(upper)},
            {"name": "Tầng 3", "rooms": copy.deepcopy(upper)},
        ],
    }


# --------------------------------------------------------------------------- typology settings
def test_typology_settings_are_sourced():
    t = load_typology("nha_pho")
    assert t.storey_heights_m == [3.9, 3.6, 3.3]
    assert t.min_storey_height_m == 3.0
    assert {"gieng_troi", "de_xe", "san_thuong"} <= set(t.kinds)
    assert t.kinds["gieng_troi"].light_well is True and t.kinds["gieng_troi"].outdoor is False
    assert t.kinds["san_thuong"].outdoor is True
    assert t.kinds["ngu"].light_well is False
    for item in (t.sources["storey_heights_m"], t.sources["balcony_projection"], t.sources["min_storey_height_m"]):
        assert item["source"] and item["needs_engineer_review"] is True


@pytest.mark.parametrize("street, expected", [(None, 0.0), (5.0, 0.0), (6.9, 0.0), (7.0, 1.2), (20.0, 1.2)])
def test_balcony_projection_by_street_width(street, expected):
    assert balcony_projection_m("nha_pho", street) == expected


# --------------------------------------------------------------------------- program defaults + validation
def test_storey_heights_default_from_rules_and_explicit_wins():
    d = _v2()
    d["floors"].append({"name": "Tầng 4", "rooms": [{"id": "ngu", "kind": "ngu", "adjacent_to": ["stair"]},
                                                     {"id": "gieng", "kind": "gieng_troi", "adjacent_to": ["ngu"]}]})
    p = Program.model_validate(d)
    assert [f.height_m for f in p.floors] == [3.9, 3.6, 3.3, 3.3]
    d["floors"][2]["height_m"] = 3.5
    assert [f.height_m for f in Program.model_validate(d).floors] == [3.9, 3.6, 3.5, 3.3]


def _mut(fn):
    d = _v2()
    fn(d)
    return d


INVALID = {
    "projecting_on_ground_floor": lambda d: d["floors"][0]["rooms"][0].update(projecting=True),
    "projecting_indoor_kind": lambda d: d["floors"][1]["rooms"][1].update(projecting=True),
    "projecting_without_street": lambda d: d["lot"].pop("street_width_m"),
    "projecting_on_narrow_street": lambda d: d["lot"].update(street_width_m=6.0),
    "light_well_gap": lambda d: d["floors"][1].update(rooms=[r for r in d["floors"][1]["rooms"] if r["id"] != "gieng"]
                                                       + [{"id": "kho", "kind": "kho", "adjacent_to": ["ngu2"]}]),
    "storey_too_low": lambda d: d["floors"][1].update(height_m=2.9),
    "storey_off_grid": lambda d: d["floors"][1].update(height_m=3.45),
    "negative_street": lambda d: d["lot"].update(street_width_m=-1.0),
}


@pytest.mark.parametrize("case", sorted(INVALID))
def test_invalid_v2_programs_are_rejected(case):
    with pytest.raises(ValidationError):
        Program.model_validate(_mut(INVALID[case]))


# --------------------------------------------------------------------------- solver
@pytest.fixture(scope="module")
def solved():
    prog = Program.model_validate(_v2())
    return prog, solve_layout(prog)


def test_v2_layout_satisfies_every_rule(solved):
    prog, lay = solved
    assert lay.stats.status in {"OPTIMAL", "FEASIBLE"}
    assert layout_violations(prog, lay.model_dump(), RULES) == []


def test_heights_and_elevations_accumulate(solved):
    _, lay = solved
    assert [f.height_mm for f in lay.floors] == [3900, 3600, 3300]
    assert [f.elevation_mm for f in lay.floors] == [0, 3900, 7500]
    assert not hasattr(lay, "storey_height_mm")


def test_projecting_balcony_sits_in_front_of_the_facade(solved):
    _, lay = solved
    x0, y0, x1, _ = lay.buildable_mm
    for fl in lay.floors[1:]:
        b = next(r for r in fl.rooms if r.id == "ban_cong")
        assert (b.y_mm, b.d_mm) == (y0 - 1200, 1200)
        assert x0 <= b.x_mm and b.x_mm + b.w_mm <= x1


def test_light_well_is_aligned_through_every_floor(solved):
    _, lay = solved
    rects = {(r.x_mm, r.y_mm, r.w_mm, r.d_mm) for fl in lay.floors for r in fl.rooms if r.id == "gieng"}
    assert len(rects) == 1


# --------------------------------------------------------------------------- building (task 023 builds these)
def test_build_ifc_builds_balconies_and_light_wells_cleanly(solved):
    from src.model_checks import run_all

    _, lay = solved
    model = build_ifc(lay)
    bad = {k: [i.message for i in v][:3] for k, v in run_all(model).items() if v}
    assert bad == {}
