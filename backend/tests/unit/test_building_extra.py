"""Unit tests for design_core.building edge cases and roof railing fallback."""

from __future__ import annotations

import ifcopenshell.util.element as ue

from src.design_core.building import build_ifc
from src.design_core.layout import Connection, FloorLayout, Layout, PlacedRoom, SolveStats
from src.model_checks import run_all


def test_single_storey_without_upper_outdoor_adds_roof_railings_and_passes_checks():
    floor = FloorLayout(
        name="Tầng 1",
        index=0,
        elevation_mm=0,
        height_mm=3600,
        rooms=[
            PlacedRoom(id="khach", kind="khach", x_mm=0, y_mm=0, w_mm=4000, d_mm=5000),
            PlacedRoom(id="wc", kind="wc", x_mm=0, y_mm=5000, w_mm=2000, d_mm=3000),
            PlacedRoom(id="bep_an", kind="bep_an", x_mm=2000, y_mm=5000, w_mm=2000, d_mm=3000),
            PlacedRoom(id="stair", kind="stair", x_mm=0, y_mm=8000, w_mm=4000, d_mm=2000),
        ],
        connections=[
            Connection(a="khach", b="wc", x0_mm=0, y0_mm=5000, x1_mm=2000, y1_mm=5000),
            Connection(a="khach", b="bep_an", x0_mm=2000, y0_mm=5000, x1_mm=4000, y1_mm=5000),
            Connection(a="wc", b="bep_an", x0_mm=2000, y0_mm=5000, x1_mm=2000, y1_mm=8000),
            Connection(a="bep_an", b="stair", x0_mm=2000, y0_mm=8000, x1_mm=4000, y1_mm=8000),
        ],
    )
    floor2 = FloorLayout(
        name="Tầng 2",
        index=1,
        elevation_mm=3600,
        height_mm=3600,
        rooms=[
            PlacedRoom(id="ngu1", kind="ngu", x_mm=0, y_mm=0, w_mm=4000, d_mm=5000),
            PlacedRoom(id="kho", kind="kho", x_mm=0, y_mm=5000, w_mm=2000, d_mm=3000),
            PlacedRoom(id="sanh", kind="sanh", x_mm=2000, y_mm=5000, w_mm=2000, d_mm=3000),
            PlacedRoom(id="stair", kind="stair", x_mm=0, y_mm=8000, w_mm=4000, d_mm=2000),
        ],
        connections=[
            Connection(a="ngu1", b="sanh", x0_mm=2000, y0_mm=5000, x1_mm=4000, y1_mm=5000),
            Connection(a="kho", b="sanh", x0_mm=2000, y0_mm=5000, x1_mm=2000, y1_mm=8000),
            Connection(a="sanh", b="stair", x0_mm=2000, y0_mm=8000, x1_mm=4000, y1_mm=8000),
        ],
    )
    layout = Layout(
        program_name="nha_test_no_balcony",
        typology="nha_pho",
        buildable_mm=(0, 0, 4000, 10000),
        floors=[floor, floor2],
        stats=SolveStats(status="OPTIMAL", objective=0.0, wall_time_s=0.01),
    )

    model = build_ifc(layout)
    railings = model.by_type("IfcRailing")
    assert len(railings) == 2
    for r in railings:
        assert ue.get_container(r).Name == "Tầng 2"

    bad = {k: [i.message for i in v] for k, v in run_all(model).items() if v}
    assert bad == {}
