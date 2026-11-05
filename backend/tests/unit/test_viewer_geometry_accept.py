"""Acceptance tests for task 017 (3D viewer shows the real IFC geometry). LOCKED.

Before: GET /api/v1/ifc/geometry/{f} returned a placeholder list read from <f>_parsed.json, so the
frontend never received `meshes` and always fell back to boxes drawn from spec numbers in JS.
Expected values below were measured with src.data_pipeline.ifc_geometry.extract_geometry on
tests/unit/ifc_fixtures.build_house().
"""

from collections import Counter
from pathlib import Path
from unittest.mock import patch

import pytest

from tests.unit.ifc_fixtures import build_house

REPO_ROOT = Path(__file__).resolve().parents[3]
LEAK = "LEAK-/app/secret/geometry"


@pytest.fixture
def ifc_dir(tmp_path, monkeypatch):
    from src.api import router_ifc
    monkeypatch.setattr(router_ifc.settings, "ifc_upload_dir", str(tmp_path))
    monkeypatch.setattr(router_ifc.settings, "ifc_geometry_cache_dir", str(tmp_path / "cache"))
    build_house().write(str(tmp_path / "house.ifc"))
    return tmp_path


def _get(client, headers, name="house.ifc"):
    return client.get(f"/api/v1/ifc/geometry/{name}", headers=headers)


def test_setting_default():
    from src.core.config import Settings
    assert Settings.model_fields["ifc_geometry_cache_dir"].default == "data/cache/geometry"


def test_returns_meshes_of_every_visible_element(client, auth_headers, ifc_dir):
    res = _get(client, auth_headers)
    assert res.status_code == 200
    body = res.json()
    meshes = body["meshes"]
    assert len(meshes) == 15  # 4 columns, footing, 2 slabs, 2 walls, door, window, beam, stair, railing, roof
    assert Counter(m["m"]["type"] for m in meshes) == Counter(
        {"Column": 4, "Slab": 2, "Wall": 2, "Beam": 1, "Door": 1, "Footing": 1,
         "Railing": 1, "Roof": 1, "Stair": 1, "Window": 1})
    for m in meshes:
        assert set(m) == {"v", "f", "c", "o", "m"}
        assert len(m["v"]) % 3 == 0 and len(m["v"]) >= 9 and len(m["f"]) % 3 == 0
        assert {"id", "type", "name"} <= set(m["m"])
    assert body["stats"]["building_name"] == "Nhà mẫu"
    assert body["stats"]["storeys"] == ["T1", "T2"]


def test_mesh_coordinates_are_metres(client, auth_headers, ifc_dir):
    stats = _get(client, auth_headers).json()["stats"]
    assert stats["bbox_min"] == pytest.approx([-0.5, -0.5, -0.5], abs=0.01)
    assert stats["bbox_max"] == pytest.approx([6.15, 8.15, 5.0], abs=0.01)


def test_mesh_ids_are_ifc_global_ids(client, auth_headers, ifc_dir):
    import ifcopenshell
    model = ifcopenshell.open(str(ifc_dir / "house.ifc"))
    ids = {m["m"]["id"] for m in _get(client, auth_headers).json()["meshes"]}
    assert all(model.by_guid(i) for i in ids)
    assert len(ids) == 15


def test_second_call_is_served_from_cache(client, auth_headers, ifc_dir):
    first = _get(client, auth_headers).json()
    assert list((ifc_dir / "cache").glob("*.json")), "cache file not written to ifc_geometry_cache_dir"
    with patch("ifcopenshell.geom.create_shape", side_effect=AssertionError("cache not used")):
        second = _get(client, auth_headers)
    assert second.status_code == 200
    assert second.json() == first


def test_missing_ifc_is_404(client, auth_headers, ifc_dir):
    assert _get(client, auth_headers, "missing.ifc").status_code == 404


def test_requires_auth(client, ifc_dir):
    assert client.get("/api/v1/ifc/geometry/house.ifc").status_code == 401


def test_extraction_failure_is_generic_500(client, auth_headers, ifc_dir):
    with patch("src.data_pipeline.ifc_geometry.extract_geometry", side_effect=RuntimeError(LEAK)), \
         patch("src.api.router_ifc.extract_geometry", side_effect=RuntimeError(LEAK), create=True):
        res = _get(client, auth_headers)
    assert res.status_code == 500
    assert LEAK not in res.text
    assert res.json()["detail"] == "Lỗi trích xuất hình học IFC."


def test_placeholder_builder_removed():
    from src.api import router_ifc
    assert not hasattr(router_ifc, "_create_viewer_geometry")


@pytest.mark.skipif(not (REPO_ROOT / "frontend").exists(), reason="frontend/ không có trong image backend")
class TestFrontend:
    def _src(self, name):
        return (REPO_ROOT / "frontend" / "js" / name).read_text(encoding="utf-8")

    def test_fallback_is_announced(self):
        src = self._src("ifc-upload.js")
        assert "Toast.warning(" in src
        assert "mô hình phác thảo" in src

    def test_viewer_can_open_an_uploaded_file(self):
        src = self._src("ifc-upload.js")
        assert "async showIfcFile(filename)" in src
        assert "data-view-ifc" in src
        assert "IFCViewer.showIfcFile(" in src
