"""Acceptance tests for task 023 (facade and roof of a real nhà phố). LOCKED.

Builds the new samples (projecting balconies, light well through the house, roof terrace, garage entrance)
and checks the elements that make the model read as a Vietnamese town house. Geometry is read back with
ifcopenshell.geom in world coordinates; "covers" uses the real triangles, not bounding boxes, so a roof with
a hole over the light well is told apart from a roof without one.
"""

import numpy as np
import ifcopenshell.geom
import ifcopenshell.util.element as ue
import pytest

from src.design_core.building import build_ifc
from src.design_core.layout import solve_layout
from src.design_core.typologies import load_rules, load_samples
from src.model_checks import run_all

SAMPLES = load_samples("nha_pho")
RULES = load_rules("nha_pho")
SLAB = 150
GEOM = ifcopenshell.geom.settings()
GEOM.set(GEOM.USE_WORLD_COORDS, True)


def _tris(el):
    s = ifcopenshell.geom.create_shape(GEOM, el)
    v = np.array(s.geometry.verts, dtype=float).reshape(-1, 3) * 1000.0
    f = np.array(s.geometry.faces, dtype=int).reshape(-1, 3)
    return v[f]  # (n, 3, 3) in mm


def _bbox(el):
    t = _tris(el).reshape(-1, 3)
    return t.min(0), t.max(0)


def _covers_xy(el, x, y):
    """True if some triangle of the element, projected on plan, contains (x, y)."""
    for a, b, c in _tris(el)[:, :, :2]:
        d = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
        if abs(d) < 1e-9:
            continue
        l1 = ((b[1] - c[1]) * (x - c[0]) + (c[0] - b[0]) * (y - c[1])) / d
        l2 = ((c[1] - a[1]) * (x - c[0]) + (a[0] - c[0]) * (y - c[1])) / d
        if l1 >= -1e-6 and l2 >= -1e-6 and l1 + l2 <= 1 + 1e-6:
            return True
    return False


def _center(r):
    return r.x_mm + r.w_mm / 2, r.y_mm + r.d_mm / 2


@pytest.fixture(scope="module", params=SAMPLES, ids=lambda p: p.name)
def built(request):
    lay = solve_layout(request.param)
    model = build_ifc(lay)
    storeys = {s.Name: s for s in model.by_type("IfcBuildingStorey")}

    def contained(fl, cls):
        return [e for e in model.by_type(cls) if ue.get_container(e) == storeys[fl.name]]

    return request.param, lay, model, contained


def test_samples_cover_the_new_features():
    lays = [solve_layout(p) for p in SAMPLES]
    kinds = {r.kind for lay in lays for fl in lay.floors for r in fl.rooms}
    assert {"gieng_troi", "de_xe", "san_thuong", "ban_cong"} <= kinds
    assert any(r.y_mm < lay.buildable_mm[1] for lay in lays for fl in lay.floors for r in fl.rooms), "thiếu ban công đua"
    assert any(r.entrance for lay in lays for r in lay.floors[0].rooms)


def test_entrance_flag_is_carried_into_the_layout(built):
    prog, lay, *_ = built
    want = {r.id for r in prog.floors[0].rooms if r.entrance}
    assert {r.id for r in lay.floors[0].rooms if r.entrance} == want
    assert all(not r.entrance for fl in lay.floors[1:] for r in fl.rooms)


def test_all_model_checks_still_clean(built):
    _, _, model, _ = built
    bad = {k: [i.message for i in v][:4] for k, v in run_all(model).items() if v}
    assert bad == {}


# --------------------------------------------------------------------------- projecting balconies
def test_projecting_balcony_has_a_slab_and_guardrails_on_three_sides(built):
    _, lay, _, contained = built
    y0 = lay.buildable_mm[1]
    for fl in lay.floors:
        for r in fl.rooms:
            if r.y_mm >= y0:
                continue
            slab = next(s for s in contained(fl, "IfcSlab") if s.PredefinedType == "FLOOR")
            cx, cy = _center(r)
            assert _covers_xy(slab, cx, cy), f"{fl.name}/{r.id}: sàn tầng không đỡ ban công đua"
            rails = [_bbox(x) for x in contained(fl, "IfcRailing")]
            z = fl.elevation_mm + SLAB + 500
            edges = {"trước": (cx, r.y_mm), "trái": (r.x_mm, cy), "phải": (r.x_mm + r.w_mm, cy)}
            for name, (px, py) in edges.items():
                ok = any(lo[0] - 60 <= px <= hi[0] + 60 and lo[1] - 60 <= py <= hi[1] + 60 and lo[2] <= z <= hi[2]
                         for lo, hi in rails)
                assert ok, f"{fl.name}/{r.id}: thiếu lan can cạnh {name}"
            assert all(hi[2] - lo[2] >= 1000 for lo, hi in rails)


# --------------------------------------------------------------------------- light well
def test_light_well_is_open_through_the_slabs_and_glazed_at_the_roof(built):
    _, lay, model, contained = built
    top = lay.floors[-1]
    wells = {r.id: r for fl in lay.floors for r in fl.rooms if r.kind != "stair" and RULES[r.kind].light_well}
    for wid, r in wells.items():
        cx, cy = _center(r)
        first = min(fl.index for fl in lay.floors for x in fl.rooms if x.id == wid)
        for fl in lay.floors:
            if fl.index <= first:
                continue
            slab = next(s for s in contained(fl, "IfcSlab") if s.PredefinedType == "FLOOR")
            # the slab of a floor above the well's first floor must leave the well open
            assert not _covers_xy(slab, cx, cy), f"{fl.name}: sàn phải để lỗ thông tầng ở giếng trời {wid}"
        roof = model.by_type("IfcRoof")[0]
        assert not _covers_xy(roof, cx, cy), f"mái không được bịt giếng trời {wid}"
        plates = [p for p in model.by_type("IfcPlate") if _covers_xy(p, cx, cy)]
        assert plates, f"thiếu mái kính trên giếng trời {wid}"
        lo, hi = _bbox(plates[0])
        assert lo[2] >= top.elevation_mm + top.height_mm - 2
        mat = ue.get_material(plates[0])
        assert mat is not None and mat.Name == "Kính"


# --------------------------------------------------------------------------- roof terrace + parapets
def test_roof_covers_indoor_rooms_but_not_terraces(built):
    _, lay, model, _ = built
    top = lay.floors[-1]
    roof = model.by_type("IfcRoof")[0]
    for r in top.rooms:
        cx, cy = _center(r)
        open_sky = r.kind != "stair" and (RULES[r.kind].outdoor or RULES[r.kind].light_well)
        assert _covers_xy(roof, cx, cy) != open_sky, f"{top.name}/{r.id}: mái {'không được che' if open_sky else 'phải che'}"


def test_parapet_walls_on_the_roof(built):
    _, lay, model, contained = built
    top = lay.floors[-1]
    roof_top = top.elevation_mm + top.height_mm + SLAB
    parapets = [w for w in contained(top, "IfcWall") if w.PredefinedType == "PARAPET"]
    assert len(parapets) >= 2, "thiếu tường chắn mái"
    for w in parapets:
        lo, hi = _bbox(w)
        assert lo[2] == pytest.approx(roof_top, abs=2) and hi[2] - lo[2] >= 1000, w.Name
        assert ue.get_pset(w, "Pset_WallCommon")["IsExternal"] is True


# --------------------------------------------------------------------------- street front
def test_garage_entrance_has_a_wide_street_door_and_a_canopy(built):
    _, lay, _, contained = built
    g = lay.floors[0]
    y0 = lay.buildable_mm[1]
    ent = next((r for r in g.rooms if r.entrance and r.kind != "stair" and not RULES[r.kind].outdoor), None)
    if ent is None:  # entrance through an open front yard: no street door or canopy required
        assert all(RULES[r.kind].outdoor for r in g.rooms if r.entrance)
        return
    doors = [_bbox(d) for d in contained(g, "IfcDoor")]
    street = [(lo, hi) for lo, hi in doors if abs((lo[1] + hi[1]) / 2 - y0) <= 150
              and ent.x_mm <= (lo[0] + hi[0]) / 2 <= ent.x_mm + ent.w_mm]
    assert street, "thiếu cửa mặt tiền cho lối vào"
    lo, hi = street[0]
    assert hi[0] - lo[0] >= 2400 and hi[2] - lo[2] >= 2400
    canopies = [s for s in contained(g, "IfcSlab") if s.PredefinedType == "ROOF"]
    assert canopies, "thiếu mái đón"
    clo, chi = _bbox(canopies[0])
    assert chi[1] <= y0 + 1 and clo[1] < y0 - 500
    assert g.elevation_mm + 2600 <= clo[2] and chi[2] <= g.elevation_mm + g.height_mm
    cx = ent.x_mm + ent.w_mm / 2
    assert clo[0] <= cx <= chi[0]


def test_facade_windows_are_generous(built):
    _, lay, _, contained = built
    x0, y0, x1, y1 = lay.buildable_mm
    for fl in lay.floors:
        wins = [_bbox(w) for w in contained(fl, "IfcWindow")]
        for r in fl.rooms:
            if r.kind in ("stair", "wc", "kho") or RULES[r.kind].outdoor or RULES[r.kind].light_well:
                continue
            for fy in (y0, y1):
                if fy not in (r.y_mm, r.y_mm + r.d_mm):
                    continue
                mine = [(lo, hi) for lo, hi in wins if abs((lo[1] + hi[1]) / 2 - fy) <= 150
                        and r.x_mm <= (lo[0] + hi[0]) / 2 <= r.x_mm + r.w_mm]
                if not mine:
                    continue  # lit through a door on this facade (allowed by test_building_accept)
                want = min(r.w_mm - 600, 2400) - 10
                assert max(hi[0] - lo[0] for lo, hi in mine) >= want, f"{fl.name}/{r.id}: cửa sổ mặt ngoài quá nhỏ"
