"""Extra unit tests for task 022 (program v2: per-floor heights, balcony projection, light wells, new kinds)."""

from __future__ import annotations

import pytest
from PIL import Image
from pydantic import ValidationError

from src.design_core.building import build_ifc
from src.design_core.draw import draw_layout
from src.design_core.layout import LayoutInfeasible, solve_layout
from src.design_core.program import Program, TypologyRules
from src.design_core.typologies import balcony_projection_m, load_rules, load_typology
from src.model_checks import run_all
from tests.unit.test_layout_accept import layout_violations

RULES = load_rules("nha_pho")


def test_typology_loader_returns_typed_model():
    typ = load_typology("nha_pho")
    assert isinstance(typ, TypologyRules)
    assert not hasattr(Program.model_fields, "storey_height_m")
    assert "storey_height_m" not in Program.model_fields


def test_light_well_starting_on_upper_floor_and_projecting_balcony(tmp_path):
    prog = Program.model_validate(
        {
            "typology": "nha_pho",
            "name": "upper_well_and_balcony",
            "lot": {"width_m": 5.0, "depth_m": 18.0, "street_width_m": 12.0},
            "stair": {"width_m": 2.2, "length_m": 4.0},
            "floors": [
                {
                    "name": "Tầng 1",
                    "height_m": 3.8,
                    "rooms": [
                        {"id": "de_xe", "kind": "de_xe", "entrance": True, "adjacent_to": ["khach"]},
                        {"id": "khach", "kind": "khach", "needs_daylight": False, "adjacent_to": ["stair", "wc"]},
                        {"id": "wc", "kind": "wc", "adjacent_to": ["bep_an"]},
                        {"id": "bep_an", "kind": "bep_an", "adjacent_to": ["stair"]},
                    ],
                },
                {
                    "name": "Tầng 2",
                    "height_m": 3.4,
                    "rooms": [
                        {"id": "ban_cong", "kind": "ban_cong", "projecting": True, "adjacent_to": ["ngu1"]},
                        {"id": "ngu1", "kind": "ngu", "adjacent_to": ["sanh"]},
                        {"id": "sanh", "kind": "sanh", "adjacent_to": ["stair"]},
                        {"id": "wc", "kind": "wc", "adjacent_to": ["sanh"]},
                        {"id": "gieng", "kind": "gieng_troi", "adjacent_to": ["ngu2"]},
                        {"id": "ngu2", "kind": "ngu", "adjacent_to": ["stair"]},
                    ],
                },
            ],
        }
    )
    lay = solve_layout(prog)
    assert [f.height_mm for f in lay.floors] == [3800, 3400]
    assert [f.elevation_mm for f in lay.floors] == [0, 3800]
    assert layout_violations(prog, lay.model_dump(), RULES) == []

    png_path = tmp_path / "upper_well_and_balcony.png"
    draw_layout(lay, png_path)
    img = Image.open(png_path)
    assert img.mode == "RGB" and img.width >= 400


def test_light_well_id_switched_to_non_light_well_on_top_floor_rejected():
    with pytest.raises(ValidationError):
        Program.model_validate(
            {
                "typology": "nha_pho",
                "name": "bad_well_kind_switch",
                "lot": {"width_m": 4.0, "depth_m": 12.0},
                "stair": {"width_m": 2.0, "length_m": 3.0},
                "floors": [
                    {
                        "name": "Tầng 1",
                        "rooms": [
                            {"id": "san", "kind": "san", "entrance": True, "adjacent_to": ["gieng"]},
                            {"id": "gieng", "kind": "gieng_troi", "adjacent_to": ["khach"]},
                            {"id": "khach", "kind": "khach", "adjacent_to": ["stair"]},
                        ],
                    },
                    {
                        "name": "Tầng 2",
                        "rooms": [
                            {"id": "gieng", "kind": "kho", "adjacent_to": ["ngu"]},
                            {"id": "ngu", "kind": "ngu", "adjacent_to": ["stair"]},
                        ],
                    },
                ],
            }
        )


def test_projecting_balcony_with_excessive_min_width_raises_infeasible():
    prog = Program.model_validate(
        {
            "typology": "nha_pho",
            "name": "too_deep_balcony",
            "lot": {"width_m": 4.0, "depth_m": 12.0, "street_width_m": 12.0},
            "stair": {"width_m": 2.0, "length_m": 3.0},
            "floors": [
                {
                    "name": "Tầng 1",
                    "rooms": [
                        {"id": "san", "kind": "san", "entrance": True, "adjacent_to": ["khach"]},
                        {"id": "khach", "kind": "khach", "adjacent_to": ["stair"]},
                    ],
                },
                {
                    "name": "Tầng 2",
                    "rooms": [
                        {
                            "id": "ban_cong",
                            "kind": "ban_cong",
                            "projecting": True,
                            "min_width_m": 1.5,
                            "adjacent_to": ["ngu"],
                        },
                        {"id": "ngu", "kind": "ngu", "adjacent_to": ["stair"]},
                    ],
                },
            ],
        }
    )
    assert balcony_projection_m("nha_pho", prog.lot.street_width_m) == 1.2
    with pytest.raises(LayoutInfeasible):
        solve_layout(prog)


def test_build_ifc_variable_floor_heights_passes_all_checks():
    prog = Program.model_validate(
        {
            "typology": "nha_pho",
            "name": "var_heights_2t",
            "lot": {"width_m": 4.0, "depth_m": 12.0},
            "stair": {"width_m": 2.2, "length_m": 4.0},
            "floors": [
                {
                    "name": "Tầng 1",
                    "height_m": 4.0,
                    "rooms": [
                        {"id": "san", "kind": "san", "entrance": True, "adjacent_to": ["khach"]},
                        {"id": "khach", "kind": "khach", "adjacent_to": ["stair"]},
                    ],
                },
                {
                    "name": "Tầng 2",
                    "height_m": 3.2,
                    "rooms": [
                        {"id": "ban_cong", "kind": "ban_cong", "adjacent_to": ["ngu"]},
                        {"id": "ngu", "kind": "ngu", "adjacent_to": ["stair"]},
                    ],
                },
            ],
        }
    )
    lay = solve_layout(prog)
    assert [f.height_mm for f in lay.floors] == [4000, 3200]
    assert [f.elevation_mm for f in lay.floors] == [0, 4000]
    model = build_ifc(lay)
    bad = {k: [i.message for i in v] for k, v in run_all(model).items() if v}
    assert bad == {}
