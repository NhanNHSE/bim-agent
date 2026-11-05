"""Acceptance tests for task 018 (scripts/render_model.py: IFC or geometry JSON -> PNG). LOCKED."""

import json

import pytest
from PIL import Image

from tests.unit.ifc_fixtures import build_house

SIZE = (1400, 700)


def _quad_mesh(z, color):
    """A 2 x 2 m horizontal square at height z (two triangles), in the /geometry mesh format."""
    v = [0, 0, z, 2, 0, z, 2, 2, z, 0, 2, z]
    return {"v": v, "f": [0, 1, 2, 0, 2, 3], "c": color, "o": 1.0, "m": {"id": f"q{z}", "type": "Slab", "name": f"q{z}"}}


def _geometry(meshes):
    return {"meshes": meshes, "stats": {"building_name": "Test", "bbox_min": [0, 0, 0], "bbox_max": [2, 2, 1],
                                        "element_counts": {"Slab": len(meshes)}}}


def _count(img, box, pred):
    return sum(1 for px in img.crop(box).getdata() if pred(px))


def _reddish(px):
    return px[0] > 100 and px[1] < 40 and px[2] < 40


def _bluish(px):
    return px[2] > 100 and px[0] < 40 and px[1] < 40


@pytest.fixture
def house_ifc(tmp_path):
    p = tmp_path / "house.ifc"
    build_house().write(str(p))
    return p


def test_render_from_ifc(house_ifc, tmp_path):
    from scripts.render_model import main
    out = tmp_path / "house.png"
    assert main([str(house_ifc), str(out), "--cache-dir", str(tmp_path / "cache")]) == 0
    img = Image.open(out).convert("RGB")
    assert img.size == SIZE
    bg = img.getpixel((SIZE[0] // 4, SIZE[1] - 2))
    left = _count(img, (0, 60, SIZE[0] // 2, SIZE[1]), lambda px: px != bg)
    right = _count(img, (SIZE[0] // 2, 60, SIZE[0], SIZE[1]), lambda px: px != bg)
    assert left > 20_000 and right > 20_000, (left, right)  # both views actually drawn
    header_dark = _count(img, (0, 0, SIZE[0], 60), lambda px: sum(px) < 200)
    assert header_dark > 50  # header text present


def test_render_returns_summary(house_ifc, tmp_path):
    from scripts.render_model import render
    from src.data_pipeline.ifc_geometry import extract_geometry
    summary = render(extract_geometry(str(house_ifc)), str(tmp_path / "a.png"))
    assert summary["meshes"] == 15
    assert summary["bbox_m"] == pytest.approx([6.65, 8.65, 5.5], abs=0.01)


def test_json_input_equals_ifc_input(house_ifc, tmp_path):
    from scripts.render_model import main
    from src.data_pipeline.ifc_geometry import extract_geometry
    j = tmp_path / "g.json"
    j.write_text(json.dumps(extract_geometry(str(house_ifc))), encoding="utf-8")
    a, b = tmp_path / "a.png", tmp_path / "b.png"
    assert main([str(house_ifc), str(a), "--cache-dir", str(tmp_path / "c")]) == 0
    assert main([str(j), str(b)]) == 0
    assert list(Image.open(a).getdata()) == list(Image.open(b).getdata())


def test_deterministic(tmp_path):
    from scripts.render_model import render
    g = _geometry([_quad_mesh(0, [1, 0, 0])])
    render(g, str(tmp_path / "1.png"))
    render(g, str(tmp_path / "2.png"))
    assert (tmp_path / "1.png").read_bytes() == (tmp_path / "2.png").read_bytes()


def test_plan_view_shows_upper_element_on_top(tmp_path):
    """Painter's order: in the plan view, a blue square at z=1 must hide the red square at z=0 below it."""
    from scripts.render_model import render
    for order in ([0, 1], [1, 0]):  # independent of mesh order in the input
        meshes = [_quad_mesh(0, [1, 0, 0]) if i == 0 else _quad_mesh(1, [0, 0, 1]) for i in order]
        out = tmp_path / f"plan_{order[0]}.png"
        render(_geometry(meshes), str(out))
        img = Image.open(out).convert("RGB")
        right = (SIZE[0] // 2, 60, SIZE[0], SIZE[1])
        assert _count(img, right, _bluish) > 10_000
        assert _count(img, right, _reddish) == 0


def test_missing_input_exit_2(tmp_path, capsys):
    from scripts.render_model import main
    assert main([str(tmp_path / "nope.ifc"), str(tmp_path / "x.png")]) == 2
    assert not (tmp_path / "x.png").exists()


def test_unsupported_extension_exit_2(tmp_path):
    from scripts.render_model import main
    bad = tmp_path / "model.txt"
    bad.write_text("x", encoding="utf-8")
    assert main([str(bad), str(tmp_path / "x.png")]) == 2
