"""Acceptance tests for task 020 (design_core.building: Layout -> complete IFC4 building). LOCKED.

Every sample nhà phố must come out as a complete LOD 200 building that passes all 8 automatic model checks
with ZERO issues, and whose elements sit where the layout says (doors on shared walls, windows on façades,
open façades for yards/balconies, columns only in the party walls, stair aligned with the stair room).
Geometry is read back with ifcopenshell.geom in world coordinates, so the tests do not trust placements.
"""

import numpy as np
import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.util.element as ue
import ifcopenshell.util.unit
import pytest
from PIL import Image

from src.design_core.building import build_ifc
from src.design_core.layout import solve_layout
from src.design_core.typologies import load_rules, load_samples
from src.model_checks import run_all

SAMPLES = load_samples("nha_pho")
RULES = load_rules("nha_pho")
SLAB_MM = 150
GEOM = ifcopenshell.geom.settings()
GEOM.set(GEOM.USE_WORLD_COORDS, True)


def _bbox(el):
    """World-space axis-aligned bounding box of an element, in mm: (min xyz, max xyz)."""
    shape = ifcopenshell.geom.create_shape(GEOM, el)
    v = np.array(shape.geometry.verts, dtype=float).reshape(-1, 3) * 1000.0
    return v.min(0), v.max(0)


def _inside(p, box, tol=1.0):
    lo, hi = box
    return all(lo[i] - tol <= p[i] <= hi[i] + tol for i in range(3))


def _center(box):
    lo, hi = box
    return (lo + hi) / 2


@pytest.fixture(scope="module", params=SAMPLES, ids=lambda p: p.name)
def built(request):
    prog = request.param
    lay = solve_layout(prog)
    model = build_ifc(lay)
    storeys = {s.Name: s for s in model.by_type("IfcBuildingStorey")}
    boxes: dict[int, tuple] = {}

    def box(el):
        if el.id() not in boxes:
            boxes[el.id()] = _bbox(el)
        return boxes[el.id()]

    def contained(storey, cls):
        return [e for e in model.by_type(cls) if ue.get_container(e) == storey]

    return prog, lay, model, storeys, box, contained


def _facades(lay):
    x0, y0, x1, y1 = lay.buildable_mm
    return x0, y0, x1, y1


# --------------------------------------------------------------------------- the headline requirement
def test_all_model_checks_are_clean(built):
    _, _, model, *_ = built
    bad = {name: [i.message for i in issues][:5] for name, issues in run_all(model).items() if issues}
    assert bad == {}


def test_schema_and_units(built):
    _, _, model, *_ = built
    assert model.schema == "IFC4"
    assert ifcopenshell.util.unit.calculate_unit_scale(model) == pytest.approx(0.001)
    assert len(model.by_type("IfcProject")) == 1 and len(model.by_type("IfcBuilding")) == 1


def test_storeys_follow_the_layout(built):
    _, lay, model, storeys, *_ = built
    got = sorted(model.by_type("IfcBuildingStorey"), key=lambda s: s.Elevation)
    assert [s.Name for s in got] == [f.name for f in lay.floors]
    assert [round(s.Elevation) for s in got] == [f.elevation_mm for f in lay.floors]


def test_one_space_per_room(built):
    _, lay, _, storeys, *_ = built
    for fl in lay.floors:
        st = storeys[fl.name]
        spaces = [o for rel in st.IsDecomposedBy for o in rel.RelatedObjects if o.is_a("IfcSpace")]
        assert sorted(s.Name for s in spaces) == sorted(r.id for r in fl.rooms), fl.name
        kind = {r.id: r.kind for r in fl.rooms}
        for s in spaces:
            want = "Cầu thang" if kind[s.Name] == "stair" else RULES[kind[s.Name]].label
            assert s.LongName == want, (fl.name, s.Name)


# --------------------------------------------------------------------------- openings
def _well_window(fl, c):
    """On floors above the ground, an opening onto a light well is a window, not a door (task 023)."""
    kinds = {r.id: r.kind for r in fl.rooms}
    return fl.index > 0 and any(kinds[i] != "stair" and RULES[kinds[i]].light_well for i in (c.a, c.b))


def _indoor_entrance(fl):
    return next((r for r in fl.rooms if r.entrance and r.kind != "stair" and not RULES[r.kind].outdoor), None)


def test_one_door_on_each_shared_wall(built):
    _, lay, _, storeys, box, contained = built
    for fl in lay.floors:
        st = storeys[fl.name]
        doors = contained(st, "IfcDoor")
        door_conns = [c for c in fl.connections if not _well_window(fl, c)]
        extra = 1 if fl.index == 0 and _indoor_entrance(fl) else 0  # street door of an indoor entrance room
        assert len(doors) == len(door_conns) + extra, fl.name
        for c in door_conns:
            mid = np.array([(c.x0_mm + c.x1_mm) / 2, (c.y0_mm + c.y1_mm) / 2])
            hits = [d for d in doors if np.hypot(*(_center(box(d))[:2] - mid)) <= 20]
            assert len(hits) == 1, f"{fl.name}: cửa {c.a}–{c.b}"
            lo, hi = box(hits[0])
            assert lo[2] == pytest.approx(fl.elevation_mm + SLAB_MM, abs=2)
            assert 2000 <= hi[2] - lo[2] <= 2400
        wins = contained(st, "IfcWindow")
        for c in fl.connections:
            if _well_window(fl, c):
                mid = np.array([(c.x0_mm + c.x1_mm) / 2, (c.y0_mm + c.y1_mm) / 2])
                assert any(np.hypot(*(_center(box(w))[:2] - mid)) <= 20 for w in wins), (
                    f"{fl.name}: thiếu cửa sổ ra giếng trời {c.a}–{c.b}")


def test_windows_on_every_indoor_facade_and_nowhere_else(built):
    _, lay, _, storeys, box, contained = built
    x0, y0, x1, y1 = _facades(lay)
    for fl in lay.floors:
        st = storeys[fl.name]
        wins = [box(w) for w in contained(st, "IfcWindow")]
        doors = [box(d) for d in contained(st, "IfcDoor")]
        well_mids = [np.array([(c.x0_mm + c.x1_mm) / 2, (c.y0_mm + c.y1_mm) / 2])
                     for c in fl.connections if _well_window(fl, c)]
        for lo, hi in wins:
            cy = (lo[1] + hi[1]) / 2
            on_well = any(np.hypot(*(((lo + hi) / 2)[:2] - m)) <= 20 for m in well_mids)
            assert on_well or min(abs(cy - y0), abs(cy - y1)) <= 150, (
                f"{fl.name}: cửa sổ không nằm trên mặt tiền/mặt sau hay giếng trời")
            assert lo[2] >= fl.elevation_mm + SLAB_MM + 500
        for r in fl.rooms:
            if r.kind == "stair" or RULES[r.kind].outdoor or RULES[r.kind].light_well:
                continue
            for fy in (y0, y1):
                if fy not in (r.y_mm, r.y_mm + r.d_mm):
                    continue
                ok = any(r.x_mm < (lo[0] + hi[0]) / 2 < r.x_mm + r.w_mm and abs((lo[1] + hi[1]) / 2 - fy) <= 150
                         for lo, hi in wins + doors)
                assert ok, f"{fl.name}/{r.id}: mặt ngoài y={fy} không có cửa sổ hay cửa đi"


# --------------------------------------------------------------------------- walls
def _edge_midpoints(r):
    x, y, w, d = r.x_mm, r.y_mm, r.w_mm, r.d_mm
    return {"front": (x + w / 2, y), "back": (x + w / 2, y + d), "left": (x, y + d / 2), "right": (x + w, y + d / 2)}


def test_walls_enclose_rooms_but_yards_and_balconies_stay_open(built):
    _, lay, _, storeys, box, contained = built
    x0, y0, x1, y1 = _facades(lay)
    for fl in lay.floors:
        st = storeys[fl.name]
        walls = [box(w) for w in contained(st, "IfcWall")]
        cols = [box(c) for c in contained(st, "IfcColumn")]
        z = fl.elevation_mm + 1000
        for r in fl.rooms:
            open_room = r.kind != "stair" and RULES[r.kind].outdoor
            projecting = r.y_mm < y0  # balcony cantilevered past the facade: open on front, left and right
            for side, (px, py) in _edge_midpoints(r).items():
                p = (px, py, z)
                on_facade = (side == "front" and py == y0) or (side == "back" and py == y1)
                if projecting and side != "back":
                    assert not any(_inside(p, b) for b in walls), f"{fl.name}/{r.id}: ban công đua mặt {side} phải hở"
                elif open_room and on_facade:
                    assert not any(_inside(p, b) for b in walls), f"{fl.name}/{r.id}: mặt {side} phải để trống"
                else:
                    assert any(_inside(p, b) for b in walls + cols), f"{fl.name}/{r.id}: thiếu tường cạnh {side}"


def test_external_walls_are_flagged(built):
    _, lay, model, storeys, box, contained = built
    x0, y0, x1, y1 = _facades(lay)
    for w in model.by_type("IfcWall"):
        pset = ue.get_pset(w, "Pset_WallCommon") or {}
        assert isinstance(pset.get("IsExternal"), bool), w.Name
    for fl in lay.floors:
        st = storeys[fl.name]
        walls = contained(st, "IfcWall")
        z = fl.elevation_mm + 1000
        for r in fl.rooms:
            if r.kind != "stair" and RULES[r.kind].outdoor:
                continue
            for side, (px, py) in _edge_midpoints(r).items():
                if (side == "front" and py == y0) or (side == "back" and py == y1):
                    host = [w for w in walls if _inside((px, py, z), box(w))]
                    assert host and all(ue.get_pset(w, "Pset_WallCommon")["IsExternal"] for w in host), (
                        f"{fl.name}/{r.id}: tường mặt ngoài phải IsExternal=True")
        for c in fl.connections:
            if c.y0_mm == c.y1_mm and c.y0_mm in (y0, y1):
                continue  # door to a projecting balcony sits in the (external) facade wall
            mid = ((c.x0_mm + c.x1_mm) / 2, (c.y0_mm + c.y1_mm) / 2, z)
            host = [w for w in walls if _inside(mid, box(w))]
            assert host and not any(ue.get_pset(w, "Pset_WallCommon")["IsExternal"] for w in host), (
                f"{fl.name}: tường giữa {c.a}–{c.b} phải IsExternal=False")


# --------------------------------------------------------------------------- structure
def test_columns_only_in_party_walls_and_full_storey_height(built):
    _, lay, _, storeys, box, contained = built
    x0, y0, x1, y1 = _facades(lay)
    for fl in lay.floors:
        h = fl.height_mm
        cols = contained(storeys[fl.name], "IfcColumn")
        assert len(cols) >= 4, fl.name
        for c in cols:
            lo, hi = box(c)
            cx = (lo[0] + hi[0]) / 2
            assert min(abs(cx - x0), abs(cx - x1)) <= 10, f"{fl.name}: cột {c.Name} không nằm trong tường biên"
            assert lo[2] == pytest.approx(fl.elevation_mm + SLAB_MM, abs=2)
            assert hi[2] == pytest.approx(fl.elevation_mm + h, abs=2)
        assert len(contained(storeys[fl.name], "IfcBeam")) >= 2, fl.name


def test_footings_under_ground_floor(built):
    _, lay, model, storeys, box, contained = built
    footings = model.by_type("IfcFooting")
    assert len(footings) >= len(contained(storeys[lay.floors[0].name], "IfcColumn"))
    assert all(box(f)[1][2] <= 1 for f in footings)


def test_slabs_and_stair_voids(built):
    _, lay, _, storeys, box, contained = built
    for fl in lay.floors:
        slabs = [s for s in contained(storeys[fl.name], "IfcSlab") if s.PredefinedType == "FLOOR"]
        assert len(slabs) == 1, fl.name
        lo, hi = box(slabs[0])
        assert lo[2] == pytest.approx(fl.elevation_mm, abs=2) and hi[2] == pytest.approx(fl.elevation_mm + SLAB_MM, abs=2)
        if fl.index > 0:
            assert slabs[0].HasOpenings, f"{fl.name}: sàn phải có lỗ mở cầu thang"


def test_stair_in_stair_room_between_each_pair_of_floors(built):
    _, lay, _, storeys, box, contained = built
    for fl in lay.floors:
        h = fl.height_mm
        stairs = contained(storeys[fl.name], "IfcStair")
        if fl.index == len(lay.floors) - 1:
            assert stairs == [], f"{fl.name}: tầng trên cùng không có thang đi lên"
            continue
        assert len(stairs) == 1, fl.name
        room = next(r for r in fl.rooms if r.id == "stair")
        lo, hi = box(stairs[0])
        assert lo[0] >= room.x_mm and hi[0] <= room.x_mm + room.w_mm
        assert lo[1] >= room.y_mm and hi[1] <= room.y_mm + room.d_mm
        assert lo[2] == pytest.approx(fl.elevation_mm + SLAB_MM, abs=2)
        assert hi[2] == pytest.approx(fl.elevation_mm + h + SLAB_MM, abs=2)


def test_roof_on_top_floor(built):
    _, lay, model, storeys, box, contained = built
    top = lay.floors[-1]
    roofs = model.by_type("IfcRoof")
    assert len(roofs) == 1 and ue.get_container(roofs[0]) == storeys[top.name]
    assert box(roofs[0])[0][2] == pytest.approx(top.elevation_mm + top.height_mm, abs=2)


def test_railings_on_upper_balconies(built):
    _, lay, _, storeys, box, contained = built
    x0, y0, x1, y1 = _facades(lay)
    total = 0
    for fl in lay.floors:
        rails = [box(r) for r in contained(storeys[fl.name], "IfcRailing")]
        total += len(rails)
        if fl.index == 0:
            continue
        for r in fl.rooms:
            if r.kind == "stair" or not RULES[r.kind].outdoor:
                continue
            fy = r.y_mm if r.y_mm < y0 else (y0 if r.y_mm == y0 else y1)  # projecting: its own front edge
            ok = any(r.x_mm < (lo[0] + hi[0]) / 2 < r.x_mm + r.w_mm and abs((lo[1] + hi[1]) / 2 - fy) <= 150
                     and hi[2] - lo[2] >= 900 for lo, hi in rails)
            assert ok, f"{fl.name}/{r.id}: thiếu lan can ở mặt ngoài"
    assert total >= 1


# --------------------------------------------------------------------------- script
def test_build_samples_script(tmp_path):
    from scripts.build_samples import main

    assert main(["--typology", "nha_pho", "--out-dir", str(tmp_path)]) == 0
    for prog in SAMPLES:
        ifc, png = tmp_path / f"{prog.name}.ifc", tmp_path / f"{prog.name}.png"
        assert ifc.exists() and png.exists(), prog.name
        model = ifcopenshell.open(str(ifc))
        assert all(not issues for issues in run_all(model).values()), prog.name
        assert Image.open(png).mode == "RGB"
