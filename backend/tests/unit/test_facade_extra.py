"""Extra unit tests for task 023 (facade, light well, roof terrace, parapets, canopy, and facade windows)."""

from __future__ import annotations

import ifcopenshell.util.element as ue

from src.design_core.building import build_ifc
from src.design_core.layout import Connection, FloorLayout, Layout, PlacedRoom, SolveStats
from src.model_checks import run_all


def test_narrow_projecting_balcony_and_horizontal_light_well_window():
    floor1 = FloorLayout(
        name="Tầng 1",
        index=0,
        elevation_mm=0,
        height_mm=3900,
        rooms=[
            PlacedRoom(id="de_xe", kind="de_xe", x_mm=0, y_mm=0, w_mm=6000, d_mm=5000, entrance=True),
            PlacedRoom(id="khach", kind="khach", x_mm=0, y_mm=5000, w_mm=6000, d_mm=4000),
            PlacedRoom(id="stair", kind="stair", x_mm=0, y_mm=9000, w_mm=2400, d_mm=4000),
            PlacedRoom(id="gieng", kind="gieng_troi", x_mm=2400, y_mm=9000, w_mm=3600, d_mm=2000),
            PlacedRoom(id="wc", kind="wc", x_mm=2400, y_mm=11000, w_mm=3600, d_mm=2000),
            PlacedRoom(id="bep_an", kind="bep_an", x_mm=0, y_mm=13000, w_mm=6000, d_mm=5000),
        ],
        connections=[
            Connection(a="de_xe", b="khach", x0_mm=0, y0_mm=5000, x1_mm=6000, y1_mm=5000),
            Connection(a="gieng", b="khach", x0_mm=2400, y0_mm=9000, x1_mm=6000, y1_mm=9000),
            Connection(a="khach", b="stair", x0_mm=0, y0_mm=9000, x1_mm=2400, y1_mm=9000),
            Connection(a="bep_an", b="stair", x0_mm=0, y0_mm=13000, x1_mm=2400, y1_mm=13000),
            Connection(a="bep_an", b="wc", x0_mm=2400, y0_mm=13000, x1_mm=6000, y1_mm=13000),
        ],
    )
    floor2 = FloorLayout(
        name="Tầng 2",
        index=1,
        elevation_mm=3900,
        height_mm=3600,
        rooms=[
            PlacedRoom(id="ban_cong", kind="ban_cong", x_mm=0, y_mm=-1200, w_mm=2000, d_mm=1200),
            PlacedRoom(id="ngu1", kind="ngu", x_mm=0, y_mm=0, w_mm=6000, d_mm=5000),
            PlacedRoom(id="sanh", kind="sanh", x_mm=0, y_mm=5000, w_mm=6000, d_mm=4000),
            PlacedRoom(id="stair", kind="stair", x_mm=0, y_mm=9000, w_mm=2400, d_mm=4000),
            PlacedRoom(id="gieng", kind="gieng_troi", x_mm=2400, y_mm=9000, w_mm=3600, d_mm=2000),
            PlacedRoom(id="wc", kind="wc", x_mm=2400, y_mm=11000, w_mm=3600, d_mm=2000),
            PlacedRoom(id="san_thuong", kind="san_thuong", x_mm=0, y_mm=13000, w_mm=6000, d_mm=5000),
        ],
        connections=[
            Connection(a="ban_cong", b="ngu1", x0_mm=0, y0_mm=0, x1_mm=2000, y1_mm=0),
            Connection(a="ngu1", b="sanh", x0_mm=0, y0_mm=5000, x1_mm=6000, y1_mm=5000),
            Connection(a="gieng", b="sanh", x0_mm=2400, y0_mm=9000, x1_mm=6000, y1_mm=9000),
            Connection(a="sanh", b="stair", x0_mm=0, y0_mm=9000, x1_mm=2400, y1_mm=9000),
            Connection(a="san_thuong", b="stair", x0_mm=0, y0_mm=13000, x1_mm=2400, y1_mm=13000),
            Connection(a="san_thuong", b="wc", x0_mm=2400, y0_mm=13000, x1_mm=6000, y1_mm=13000),
        ],
    )
    layout = Layout(
        program_name="nha_test_facade_extra",
        typology="nha_pho",
        buildable_mm=(0, 0, 6000, 18000),
        floors=[floor1, floor2],
        stats=SolveStats(status="OPTIMAL", objective=0.0, wall_time_s=0.01),
    )

    model = build_ifc(layout)
    bad = {k: [i.message for i in v] for k, v in run_all(model).items() if v}
    assert bad == {}

    plates = model.by_type("IfcPlate")
    assert len(plates) == 1
    assert ue.get_material(plates[0]).Name == "Kính"

    parapets = [w for w in model.by_type("IfcWall") if w.PredefinedType == "PARAPET"]
    assert len(parapets) == 4
