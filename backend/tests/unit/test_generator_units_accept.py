"""Acceptance tests for task 016 (generator unit scale). LOCKED.

Both generators write a millimetre model but passed millimetre numbers to ifcopenshell.api
geometry functions, which take SI metres -> placements and API-built shapes were 1000x too big
(a 3.5 m storey ended up 3.5 km high). Measured on main before the fix: default building
bounding box 12600 x 8600 x 11600 m.
"""

import json
from pathlib import Path

import numpy as np
import ifcopenshell
import ifcopenshell.geom
import pytest

from src.data_pipeline.ifc_bridge_generator import BridgeSpec, generate_bridge
from src.data_pipeline.ifc_generator_v2 import BuildingSpec, generate_from_spec
from src.model_checks import check_extent

BACKEND = Path(__file__).resolve().parents[2]

# Baseline counts on main before this task (eval/model_baseline.json at commit of PR #17).
OLD_BASELINE = {
    "default_3t": {"schema": 30, "required_classes": 4, "openings": 15, "wall_connections": 12,
                   "columns_on_grid": 0, "spaces": 3, "extent": 52, "clashes": 57},
    "nha_pho_4t": {"schema": 66, "required_classes": 4, "openings": 20, "wall_connections": 16,
                   "columns_on_grid": 0, "spaces": 4, "extent": 96, "clashes": 124},
    "van_phong_6t": {"schema": 138, "required_classes": 3, "openings": 30, "wall_connections": 24,
                     "columns_on_grid": 1, "spaces": 6, "extent": 184, "clashes": 294},
}


def _bbox_m(path: str) -> tuple[np.ndarray, np.ndarray]:
    """World-coordinate bounding box (metres) of every element with a body, openings excluded."""
    model = ifcopenshell.open(path)
    settings = ifcopenshell.geom.settings()
    settings.set(settings.USE_WORLD_COORDS, True)
    els = [e for e in model.by_type("IfcElement") if e.Representation and not e.is_a("IfcOpeningElement")]
    it = ifcopenshell.geom.iterator(settings, model, include=els)
    lo, hi = np.full(3, np.inf), np.full(3, -np.inf)
    assert it.initialize()
    while True:
        v = np.array(it.get().geometry.verts).reshape(-1, 3)
        lo, hi = np.minimum(lo, v.min(0)), np.maximum(hi, v.max(0))
        if not it.next():
            break
    return lo, hi


@pytest.mark.parametrize("spec", [
    BuildingSpec(),
    BuildingSpec(num_storeys=4, footprint_length=18000, footprint_width=5000,
                 column_spacing_x=4500, column_spacing_y=5000),
    BuildingSpec(num_storeys=6, footprint_length=30000, footprint_width=15000),
], ids=["default_3t", "nha_pho_4t", "van_phong_6t"])
def test_building_has_real_size(spec, tmp_path):
    lo, hi = _bbox_m(generate_from_spec(spec, output_dir=str(tmp_path)))
    size = hi - lo
    length_m, width_m = spec.footprint_length / 1000, spec.footprint_width / 1000
    height_m = spec.num_storeys * spec.storey_height / 1000
    # footprint plus at most 1.5 m of overhang (column halves, footings, wall thickness)
    assert length_m <= size[0] <= length_m + 1.5, size
    assert width_m <= size[1] <= width_m + 1.5, size
    # storeys stacked, plus at most 4 m for foundation, roof slab and railing
    assert height_m - 0.5 <= size[2] <= height_m + 4.0, size
    assert np.abs(lo).max() < 5.0 and np.abs(hi).max() < 60.0


def test_storey_elevations_in_project_units(tmp_path):
    spec = BuildingSpec(num_storeys=3, storey_height=3500.0)
    model = ifcopenshell.open(generate_from_spec(spec, output_dir=str(tmp_path)))
    import ifcopenshell.util.placement as up
    zs = sorted(float(up.get_local_placement(s.ObjectPlacement)[2, 3]) for s in model.by_type("IfcBuildingStorey"))
    assert zs == pytest.approx([0.0, 3500.0, 7000.0], abs=1.0)  # mm, the model's length unit


@pytest.mark.parametrize("ifc_class", ["IfcWall", "IfcDoor", "IfcWindow", "IfcColumn", "IfcBeam"])
def test_elements_sit_inside_their_storey(ifc_class, tmp_path):
    """Upper-storey elements used to be placed at storey-1 height (local z treated as absolute)."""
    import ifcopenshell.util.element as ue
    import ifcopenshell.util.placement as up
    spec = BuildingSpec(num_storeys=3, storey_height=3500.0)
    model = ifcopenshell.open(generate_from_spec(spec, output_dir=str(tmp_path)))
    checked = 0
    for el in model.by_type(ifc_class):
        storey = ue.get_container(el)
        if storey is None or not storey.is_a("IfcBuildingStorey"):
            continue
        elev = float(up.get_local_placement(storey.ObjectPlacement)[2, 3])
        z = float(up.get_local_placement(el.ObjectPlacement)[2, 3])
        assert elev - 1.0 <= z < elev + spec.storey_height, f"{el.Name}: z={z} mm, storey {storey.Name} at {elev} mm"
        checked += 1
    if ifc_class != "IfcColumn":  # the 3-storey default has no columns (separate issue)
        assert checked > 0


def test_bridge_has_real_size(tmp_path):
    spec = BridgeSpec()
    path = generate_bridge(spec, output_dir=str(tmp_path))
    lo, hi = _bbox_m(path)
    size = hi - lo
    total_m = spec.total_length / 1000
    assert total_m <= max(size[0], size[1]) <= total_m + 15.0, size  # deck length + abutments
    assert spec.deck_width / 1000 - 0.5 <= min(size[0], size[1]) <= spec.deck_width / 1000 + 10.0, size
    # piles + pile cap + pier + girder + deck + barrier, plus 3 m slack (bearings, abutment footing)
    stack_m = (spec.pile_depth + spec.pile_cap_thickness + spec.pier_height + spec.girder_height
               + spec.deck_thickness + spec.barrier_height) / 1000
    assert spec.pier_height / 1000 <= size[2] <= stack_m + 3.0, size
    assert check_extent(ifcopenshell.open(path)) == []


def test_baseline_ratcheted_down():
    baseline = json.loads((BACKEND / "eval" / "model_baseline.json").read_text(encoding="utf-8"))["cases"]
    assert list(baseline) == list(OLD_BASELINE)
    for case, old in OLD_BASELINE.items():
        new = baseline[case]
        assert new["extent"] == 0, case
        for check, old_count in old.items():
            assert new[check] <= old_count, f"{case}/{check}: {old_count} -> {new[check]}"
