"""Acceptance tests for task 019 (design_core: program schema + CP-SAT floor-plan layout for nhà phố). LOCKED.

`layout_violations` is an independent checker of every hard rule in the spec; it reads only plain data
(`Layout.model_dump()`), so it does not trust the implementation.
"""

import copy
import time

import pytest
from PIL import Image
from pydantic import ValidationError

from src.design_core.layout import Layout, LayoutInfeasible, solve_layout
from src.design_core.program import Program
from src.design_core.typologies import load_rules, load_samples

GRID = 100  # mm


# --------------------------------------------------------------------------- independent checker
def _shared_segment(a, b):
    """Shared boundary of two axis-aligned rectangles (mm dicts) as (x0, y0, x1, y1), or None."""
    ax, ay, aw, ad = a["x_mm"], a["y_mm"], a["w_mm"], a["d_mm"]
    bx, by, bw, bd = b["x_mm"], b["y_mm"], b["w_mm"], b["d_mm"]
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


def layout_violations(program, lay: dict, rules) -> list[str]:
    v: list[str] = []
    lot = program.lot
    exp_build = (0, round(lot.front_setback_m * 1000), round(lot.width_m * 1000),
                 round((lot.depth_m - lot.back_setback_m) * 1000))
    if tuple(lay["buildable_mm"]) != exp_build:
        v.append(f"buildable_mm {lay['buildable_mm']} != {exp_build}")
    x0, y0, x1, y1 = exp_build
    build_area = (x1 - x0) * (y1 - y0)
    sh = round(program.storey_height_m * 1000)
    if lay["storey_height_mm"] != sh:
        v.append("storey_height_mm sai")
    if len(lay["floors"]) != len(program.floors):
        return v + ["số tầng sai"]
    stair_rects = set()
    for i, (fp, fl) in enumerate(zip(program.floors, lay["floors"])):
        t = fp.name
        if (fl["name"], fl["index"], fl["elevation_mm"]) != (fp.name, i, i * sh):
            v.append(f"{t}: name/index/elevation sai")
        ids = [r.id for r in fp.rooms] + (["stair"] if program.stair else [])
        if [r["id"] for r in fl["rooms"]] != ids:
            v.append(f"{t}: danh sách phòng {[r['id'] for r in fl['rooms']]} != {ids}")
            continue
        rooms = {r["id"]: r for r in fl["rooms"]}
        for r in fl["rooms"]:
            x, y, w, d = r["x_mm"], r["y_mm"], r["w_mm"], r["d_mm"]
            if any(val % GRID for val in (x, y, w, d)):
                v.append(f"{t}/{r['id']}: không nằm trên lưới 100 mm")
            if w <= 0 or d <= 0 or x < x0 or y < y0 or x + w > x1 or y + d > y1:
                v.append(f"{t}/{r['id']}: ra ngoài phạm vi xây dựng")
        if sum(r["w_mm"] * r["d_mm"] for r in fl["rooms"]) != build_area:
            v.append(f"{t}: tổng diện tích phòng != diện tích xây dựng (không phủ kín)")
        lst = fl["rooms"]
        for a_i in range(len(lst)):
            for b_i in range(a_i + 1, len(lst)):
                a, b = lst[a_i], lst[b_i]
                ix = min(a["x_mm"] + a["w_mm"], b["x_mm"] + b["w_mm"]) - max(a["x_mm"], b["x_mm"])
                iy = min(a["y_mm"] + a["d_mm"], b["y_mm"] + b["d_mm"]) - max(a["y_mm"], b["y_mm"])
                if ix > 0 and iy > 0:
                    v.append(f"{t}: {a['id']} chồng lên {b['id']}")
        neigh: dict[str, set[str]] = {r: set() for r in ids}
        pairs = set()
        for req in fp.rooms:
            for o in req.adjacent_to:
                neigh[req.id].add(o)
                neigh[o].add(req.id)
                pairs.add(tuple(sorted((req.id, o))))
        kind_of = {req.id: req.kind for req in fp.rooms}
        for req in fp.rooms:
            r = rooms[req.id]
            w, d = r["w_mm"], r["d_mm"]
            if r["kind"] != req.kind:
                v.append(f"{t}/{req.id}: kind sai")
            if min(w, d) < round(req.min_width_m * 1000):
                v.append(f"{t}/{req.id}: hẹp hơn {req.min_width_m} m")
            if w * d < req.min_area_m2 * 1e6 - 1:
                v.append(f"{t}/{req.id}: nhỏ hơn {req.min_area_m2} m²")
            if max(w, d) > req.max_aspect * min(w, d) + 1e-6:
                v.append(f"{t}/{req.id}: tỉ lệ cạnh > {req.max_aspect}")
            front, back = r["y_mm"] == y0, r["y_mm"] + d == y1
            outdoor = rules[req.kind].outdoor
            if outdoor and not (front or back):
                v.append(f"{t}/{req.id}: không gian ngoài trời không chạm mặt tiền/mặt sau")
            if req.entrance and not front:
                v.append(f"{t}/{req.id}: lối vào không chạm mặt tiền")
            if req.needs_daylight and not outdoor:
                lit_by_outdoor = any(n != "stair" and rules[kind_of[n]].outdoor for n in neigh[req.id])
                if not (lit_by_outdoor or front or back):
                    v.append(f"{t}/{req.id}: cần chiếu sáng tự nhiên nhưng không chạm mặt ngoài")
        if program.stair:
            s = rooms["stair"]
            if s["kind"] != "stair" or (s["w_mm"], s["d_mm"]) != (round(program.stair.width_m * 1000),
                                                                   round(program.stair.length_m * 1000)):
                v.append(f"{t}: cầu thang sai loại hoặc sai kích thước")
            stair_rects.add((s["x_mm"], s["y_mm"], s["w_mm"], s["d_mm"]))
        conns = [(c["a"], c["b"]) for c in fl["connections"]]
        if conns != sorted(pairs):
            v.append(f"{t}: connections {conns} != {sorted(pairs)}")
            continue
        for c in fl["connections"]:
            seg = _shared_segment(rooms[c["a"]], rooms[c["b"]])
            length = 0 if seg is None else (seg[2] - seg[0]) + (seg[3] - seg[1])
            if seg is None or length < round(program.min_shared_m * 1000):
                v.append(f"{t}: {c['a']}–{c['b']} chung cạnh {length} mm < {program.min_shared_m} m")
            elif seg != (c["x0_mm"], c["y0_mm"], c["x1_mm"], c["y1_mm"]):
                v.append(f"{t}: đoạn chung {c['a']}–{c['b']} sai: {seg}")
    if len(stair_rects) > 1:
        v.append(f"cầu thang không thẳng hàng giữa các tầng: {sorted(stair_rects)}")
    return v


# --------------------------------------------------------------------------- fixtures
RULES = load_rules("nha_pho")
SAMPLES = load_samples("nha_pho")


def _base() -> dict:
    return {
        "typology": "nha_pho", "name": "base", "lot": {"width_m": 4.0, "depth_m": 12.0},
        "stair": {"width_m": 2.2, "length_m": 4.0},
        "floors": [
            {"name": "Tầng 1", "rooms": [
                {"id": "san", "kind": "san", "entrance": True, "adjacent_to": ["khach"]},
                {"id": "khach", "kind": "khach", "adjacent_to": ["stair"]},
            ]},
            {"name": "Tầng 2", "rooms": [
                {"id": "ngu", "kind": "ngu", "min_width_m": 3.0, "adjacent_to": ["stair"]},
            ]},
        ],
    }


# --------------------------------------------------------------------------- data pack
def test_rules_cover_kinds_and_flag_unsourced_rules():
    need = {"san", "ban_cong", "giat_phoi", "khach", "bep_an", "ngu", "tho", "wc", "sanh", "hanh_lang", "kho"}
    assert need <= set(RULES)
    for kind, r in RULES.items():
        assert r.min_width_m > 0 and r.min_area_m2 > 0 and r.max_aspect >= 1, kind
        assert r.label and r.source, kind
        if not r.source.upper().startswith(("QCVN", "TCVN")):
            assert r.needs_engineer_review is True, kind


def test_samples_load_as_programs():
    assert len(SAMPLES) >= 3
    assert all(isinstance(p, Program) for p in SAMPLES)
    assert len({p.name for p in SAMPLES}) == len(SAMPLES)


def test_room_defaults_come_from_rules():
    p = Program.model_validate(_base())
    assert p.min_shared_m == 1.2
    assert p.storey_height_m == 3.6
    assert (p.lot.front_setback_m, p.lot.back_setback_m) == (0, 0)
    khach = p.floors[0].rooms[1]
    k = RULES["khach"]
    assert (khach.min_width_m, khach.min_area_m2, khach.max_aspect, khach.needs_daylight) == (
        k.min_width_m, k.min_area_m2, k.max_aspect, k.needs_daylight)
    assert khach.target_area_m2 == k.min_area_m2
    assert p.floors[1].rooms[0].min_width_m == 3.0  # explicit value wins over the rule


def _mut(fn):
    d = copy.deepcopy(_base())
    fn(d)
    return d


INVALID = {
    "unknown_kind": lambda d: d["floors"][0]["rooms"][1].update(kind="garage"),
    "duplicate_id": lambda d: d["floors"][0]["rooms"][1].update(id="san"),
    "unknown_adjacency": lambda d: d["floors"][0]["rooms"][1].update(adjacent_to=["stair", "bep"]),
    "self_adjacency": lambda d: d["floors"][0]["rooms"][1].update(adjacent_to=["stair", "khach"]),
    "stair_as_room_id": lambda d: d["floors"][1]["rooms"][0].update(id="stair"),
    "multi_floor_without_stair": lambda d: d.pop("stair"),
    "no_entrance_on_ground": lambda d: d["floors"][0]["rooms"][0].update(entrance=False),
    "entrance_on_upper_floor": lambda d: d["floors"][1]["rooms"][0].update(entrance=True),
    "two_entrances": lambda d: d["floors"][0]["rooms"][1].update(entrance=True),
    "disconnected": lambda d: d["floors"][0]["rooms"][1].update(adjacent_to=[]),
    "lot_off_grid": lambda d: d["lot"].update(width_m=4.05),
    "stair_off_grid": lambda d: d["stair"].update(length_m=3.95),
    "no_floors": lambda d: d.update(floors=[]),
}


@pytest.mark.parametrize("case", sorted(INVALID))
def test_invalid_programs_are_rejected(case):
    with pytest.raises(ValidationError):
        Program.model_validate(_mut(INVALID[case]))


def test_single_floor_without_stair_is_valid():
    d = _base()
    d.pop("stair")
    d["floors"] = [{"name": "Tầng 1", "rooms": [
        {"id": "san", "kind": "san", "entrance": True, "adjacent_to": ["khach"]},
        {"id": "khach", "kind": "khach"},
    ]}]
    assert Program.model_validate(d).stair is None


# --------------------------------------------------------------------------- checker self-test
def test_checker_catches_a_broken_layout():
    prog = SAMPLES[0]
    lay = solve_layout(prog).model_dump()
    assert layout_violations(prog, lay, RULES) == []
    broken = copy.deepcopy(lay)
    broken["floors"][0]["rooms"][0]["w_mm"] -= GRID  # leaves a gap
    assert layout_violations(prog, broken, RULES)


# --------------------------------------------------------------------------- solver
@pytest.mark.parametrize("prog", SAMPLES, ids=lambda p: p.name)
def test_sample_layout_satisfies_every_rule(prog):
    t0 = time.perf_counter()
    layout = solve_layout(prog)
    elapsed = time.perf_counter() - t0
    assert isinstance(layout, Layout)
    assert layout.program_name == prog.name and layout.typology == "nha_pho"
    assert layout.stats.status in {"OPTIMAL", "FEASIBLE"}
    assert layout_violations(prog, layout.model_dump(), RULES) == []
    assert elapsed < 20, f"{prog.name} giải mất {elapsed:.1f} s"


def test_layout_is_deterministic():
    a = solve_layout(SAMPLES[1]).model_dump(exclude={"stats"})
    b = solve_layout(SAMPLES[1]).model_dump(exclude={"stats"})
    assert a == b


def test_too_little_area_is_reported_in_vietnamese():
    d = {"typology": "nha_pho", "name": "chat", "lot": {"width_m": 4.0, "depth_m": 10.0}, "floors": [
        {"name": "Tầng 1", "rooms": [
            {"id": "san", "kind": "san", "entrance": True, "min_area_m2": 25, "adjacent_to": ["khach"]},
            {"id": "khach", "kind": "khach", "min_area_m2": 20},
        ]}]}
    with pytest.raises(LayoutInfeasible) as e:
        solve_layout(Program.model_validate(d))
    assert "diện tích" in str(e.value).lower()


def test_geometrically_impossible_program_raises():
    d = {"typology": "nha_pho", "name": "hep", "lot": {"width_m": 3.0, "depth_m": 12.0}, "floors": [
        {"name": "Tầng 1", "rooms": [
            {"id": "san", "kind": "san", "entrance": True, "adjacent_to": ["ngu"]},
            {"id": "ngu", "kind": "ngu", "min_width_m": 3.2},
        ]}]}
    with pytest.raises(LayoutInfeasible) as e:
        solve_layout(Program.model_validate(d))
    assert str(e.value).strip()
    assert issubclass(LayoutInfeasible, ValueError)


# --------------------------------------------------------------------------- script
def test_layout_samples_script_writes_json_and_png(tmp_path):
    from scripts.layout_samples import main

    assert main(["--typology", "nha_pho", "--out-dir", str(tmp_path)]) == 0
    for prog in SAMPLES:
        js, png = tmp_path / f"{prog.name}.json", tmp_path / f"{prog.name}.png"
        assert js.exists() and png.exists(), prog.name
        lay = Layout.model_validate_json(js.read_text(encoding="utf-8"))
        assert layout_violations(prog, lay.model_dump(), RULES) == []
        img = Image.open(png)
        assert img.mode == "RGB" and img.width >= 400
        assert len(img.getcolors(maxcolors=1 << 16) or range(9999)) > 5  # not a blank image
