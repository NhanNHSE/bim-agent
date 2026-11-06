"""Acceptance tests for task 021 (materials + colours that reach the 3D viewer). LOCKED.

1. Every element built by design_core.build_ifc carries an IfcMaterial with the expected Vietnamese name.
2. The geometry JSON the web viewer receives (extract_geometry) uses those material colours/transparency.
   Before this task the extractor read `mat.diffuse[0]` on an ifcopenshell `colour` object, which raises,
   and the bare `except` silently fell back to the per-class default colours.
3. Models without any style (e.g. the old generator) keep the per-class default colours.
4. Geometry caches written by the previous extractor version are not reused.
"""

import json

import ifcopenshell.util.element as ue
import pytest

from src.data_pipeline import ifc_geometry
from src.data_pipeline.ifc_geometry import TYPE_COLORS, TYPE_OPACITY, extract_geometry
from src.design_core.building import build_ifc
from src.design_core.layout import solve_layout
from src.design_core.typologies import load_samples
from tests.unit.ifc_fixtures import build_house

SAMPLES = load_samples("nha_pho")

# name, RGB 0-1, transparency
CONCRETE = ("Bê tông cốt thép", (0.70, 0.70, 0.68), 0.0)
FLOOR = ("Sàn bê tông lát gạch men", (0.87, 0.83, 0.76), 0.0)
ROOF = ("Mái bê tông chống thấm", (0.55, 0.57, 0.60), 0.0)
WALL_EXT = ("Tường gạch sơn ngoài", (0.96, 0.94, 0.89), 0.0)
WALL_INT = ("Tường gạch sơn trong", (0.99, 0.98, 0.96), 0.0)
WOOD = ("Gỗ", (0.52, 0.34, 0.20), 0.0)
GLASS = ("Kính", (0.55, 0.75, 0.88), 0.5)
STEEL = ("Thép sơn", (0.22, 0.24, 0.27), 0.0)

BY_CLASS = {"IfcColumn": CONCRETE, "IfcBeam": CONCRETE, "IfcFooting": CONCRETE, "IfcStair": CONCRETE,
            "IfcSlab": FLOOR, "IfcRoof": ROOF, "IfcDoor": WOOD, "IfcWindow": GLASS, "IfcRailing": STEEL}
BY_MESH_TYPE = {k.removeprefix("Ifc"): v for k, v in BY_CLASS.items()}


def _expected(el):
    if el.is_a("IfcWall"):
        ext = (ue.get_pset(el, "Pset_WallCommon") or {}).get("IsExternal")
        return WALL_EXT if ext else WALL_INT
    return BY_CLASS[el.is_a()]


@pytest.fixture(scope="module", params=SAMPLES, ids=lambda p: p.name)
def built(request, tmp_path_factory):
    model = build_ifc(solve_layout(request.param))
    path = tmp_path_factory.mktemp("m") / f"{request.param.name}.ifc"
    model.write(str(path))
    return model, path


def test_every_element_has_its_material(built):
    model, _ = built
    elements = [e for e in model.by_type("IfcElement") if not e.is_a("IfcFeatureElement")]
    assert elements
    for el in elements:
        mat = ue.get_material(el)
        assert mat is not None, f"{el.Name} thiếu vật liệu"
        assert mat.is_a("IfcMaterial") and mat.Name == _expected(el)[0], (el.Name, mat)


def test_viewer_geometry_uses_material_colours(built):
    _, path = built
    g = extract_geometry(str(path))
    assert g["meshes"]
    for mesh in g["meshes"]:
        t = mesh["m"]["type"]
        if t == "Wall":
            ext = str((mesh["m"].get("properties") or {}).get("IsExternal")) == "True"
            name, rgb, transp = WALL_EXT if ext else WALL_INT
        else:
            name, rgb, transp = BY_MESH_TYPE[t]
        assert mesh["c"] == pytest.approx(list(rgb), abs=0.02), (mesh["m"]["name"], name, mesh["c"])
        assert mesh["o"] == pytest.approx(1.0 - transp, abs=0.05), (mesh["m"]["name"], mesh["o"])


def test_unstyled_models_keep_type_colours(tmp_path):
    path = tmp_path / "plain.ifc"
    build_house().write(str(path))
    g = extract_geometry(str(path))
    by_type = {m["m"]["type"]: m for m in g["meshes"]}
    assert by_type["Wall"]["c"] == pytest.approx(list(TYPE_COLORS["IfcWall"]), abs=0.01)
    assert by_type["Column"]["c"] == pytest.approx(list(TYPE_COLORS["IfcColumn"]), abs=0.01)
    assert by_type["Window"]["o"] == pytest.approx(TYPE_OPACITY["IfcWindow"], abs=0.01)


def test_cache_from_previous_extractor_version_is_ignored(built, tmp_path):
    _, path = built
    cache = tmp_path / "cache"
    cache.mkdir()
    stale = cache / f"{ifc_geometry._file_hash(str(path))}_v2.json"
    stale.write_text(json.dumps({"meshes": [], "stats": {"stale": True}}), encoding="utf-8")
    g1 = extract_geometry(str(path), cache_dir=str(cache))
    assert g1["meshes"] and not g1["stats"].get("stale")
    g2 = extract_geometry(str(path), cache_dir=str(cache))
    assert [m["c"] for m in g2["meshes"]] == [m["c"] for m in g1["meshes"]]
