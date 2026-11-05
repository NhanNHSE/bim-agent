"""Additional unit tests for design_core modules and layout_samples CLI."""

from __future__ import annotations

import pytest
from PIL import Image
from pydantic import ValidationError

from scripts.layout_samples import main as layout_samples_main
from src.design_core import (
    Layout,
    LayoutInfeasible,
    Program,
    draw_layout,
    load_rules,
    solve_layout,
)
from tests.unit.test_layout_accept import layout_violations


def test_setbacks_and_single_floor_solve(tmp_path):
    prog = Program.model_validate(
        {
            "typology": "nha_pho",
            "name": "single_setback",
            "lot": {
                "width_m": 4.0,
                "depth_m": 14.0,
                "front_setback_m": 1.0,
                "back_setback_m": 1.0,
            },
            "floors": [
                {
                    "name": "Tầng 1",
                    "rooms": [
                        {
                            "id": "san",
                            "kind": "san",
                            "entrance": True,
                            "target_area_m2": 8.0,
                            "adjacent_to": ["khach"],
                        },
                        {
                            "id": "khach",
                            "kind": "khach",
                            "target_area_m2": 20.0,
                            "adjacent_to": ["bep_an"],
                        },
                        {
                            "id": "bep_an",
                            "kind": "bep_an",
                            "target_area_m2": 20.0,
                        },
                    ],
                }
            ],
        }
    )
    layout = solve_layout(prog)
    assert isinstance(layout, Layout)
    assert layout.buildable_mm == (0, 1000, 4000, 13000)
    assert layout_violations(prog, layout.model_dump(), load_rules("nha_pho")) == []

    png_path = tmp_path / "single_setback.png"
    draw_layout(layout, png_path, px_per_m=36)
    img = Image.open(png_path)
    assert img.mode == "RGB" and img.width >= 400


def test_setback_off_grid_rejected():
    with pytest.raises(ValidationError):
        Program.model_validate(
            {
                "typology": "nha_pho",
                "name": "bad_setback",
                "lot": {"width_m": 4.0, "depth_m": 12.0, "front_setback_m": 0.15},
                "floors": [
                    {
                        "name": "Tầng 1",
                        "rooms": [{"id": "san", "kind": "san", "entrance": True}],
                    }
                ],
            }
        )


def test_layout_samples_returns_nonzero_on_infeasible(tmp_path, monkeypatch, capsys):
    infeasible_prog = Program.model_validate(
        {
            "typology": "nha_pho",
            "name": "impossible_prog",
            "lot": {"width_m": 4.0, "depth_m": 8.0},
            "floors": [
                {
                    "name": "Tầng 1",
                    "rooms": [
                        {
                            "id": "san",
                            "kind": "san",
                            "entrance": True,
                            "min_area_m2": 20.0,
                            "adjacent_to": ["khach"],
                        },
                        {
                            "id": "khach",
                            "kind": "khach",
                            "min_area_m2": 20.0,
                        },
                    ],
                }
            ],
        }
    )
    monkeypatch.setattr("scripts.layout_samples.load_samples", lambda _typ: [infeasible_prog])
    rc = layout_samples_main(["--typology", "nha_pho", "--out-dir", str(tmp_path)])
    assert rc == 1
    captured = capsys.readouterr()
    assert "impossible_prog" in captured.err


def test_infeasible_unsatisfiable_constraints_raises():
    prog = Program.model_validate(
        {
            "typology": "nha_pho",
            "name": "unsat_daylight",
            "lot": {"width_m": 4.0, "depth_m": 15.0},
            "floors": [
                {
                    "name": "Tầng 1",
                    "rooms": [
                        {
                            "id": "khach",
                            "kind": "khach",
                            "entrance": True,
                            "min_width_m": 4.0,
                            "adjacent_to": ["ngu1"],
                        },
                        {
                            "id": "ngu1",
                            "kind": "ngu",
                            "min_width_m": 4.0,
                            "adjacent_to": ["ngu2"],
                        },
                        {
                            "id": "ngu2",
                            "kind": "ngu",
                            "min_width_m": 4.0,
                        },
                    ],
                }
            ],
        }
    )
    with pytest.raises(LayoutInfeasible):
        solve_layout(prog, max_deterministic_time=2.0)
