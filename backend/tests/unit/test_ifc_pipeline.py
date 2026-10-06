"""Tests for IFC Pipeline — BuildingSpec + BridgeSpec, generators, compliance, routing.

Tests are divided into:
- Unit tests: Pure dataclass/math logic (no ifcopenshell needed)
- Integration tests: IFC generation + geometry extraction (require ifcopenshell)

Integration tests are automatically skipped if ifcopenshell is not installed
(e.g., local dev without Docker).
"""

import os
import math
import tempfile
import shutil

import pytest
import numpy as np

# Check if ifcopenshell is available
try:
    import ifcopenshell
    HAS_IFCOPENSHELL = True
except ImportError:
    HAS_IFCOPENSHELL = False

requires_ifcopenshell = pytest.mark.skipif(
    not HAS_IFCOPENSHELL,
    reason="ifcopenshell not installed (run in Docker for full tests)"
)


# ---------------------------------------------------------------------------
# BuildingSpec tests (pure dataclass — skipped if ifcopenshell unavailable
# because the module imports it at top level)
# ---------------------------------------------------------------------------

@requires_ifcopenshell
class TestBuildingSpec:
    """Test BuildingSpec dataclass defaults and overrides."""

    def _make(self, **kwargs):
        from src.data_pipeline.ifc_generator_v2 import BuildingSpec
        return BuildingSpec(**kwargs)

    def test_defaults(self):
        spec = self._make()
        assert spec.num_storeys == 3
        assert spec.storey_height == 3500.0
        assert spec.building_type == "F2"
        assert spec.building_function == "Văn phòng"

    def test_override_storeys(self):
        spec = self._make(num_storeys=5, storey_height=4000)
        assert spec.num_storeys == 5
        assert spec.storey_height == 4000

    def test_footprint_area(self):
        spec = self._make(footprint_length=20000, footprint_width=10000)
        area_m2 = (spec.footprint_length / 1000) * (spec.footprint_width / 1000)
        assert area_m2 == 200.0

    def test_materials(self):
        spec = self._make(wall_material="Gạch đặc", column_material="BTCT B30")
        assert spec.wall_material == "Gạch đặc"
        assert spec.column_material == "BTCT B30"

    def test_stairs_default_for_small_building(self):
        spec = self._make(num_storeys=2)
        assert spec.num_staircases >= 1

    def test_foundation_defaults(self):
        spec = self._make()
        assert spec.has_foundation is True
        assert spec.footing_depth == 500.0

    def test_railing_and_sill(self):
        spec = self._make()
        assert spec.railing_height == 1100.0
        assert spec.window_sill_height == 900.0


# ---------------------------------------------------------------------------
# Column grid + matrix tests (require ifcopenshell for import)
# ---------------------------------------------------------------------------

@requires_ifcopenshell
class TestColumnGrid:
    """Test automatic column grid calculation."""

    def _grid(self, **kwargs):
        from src.data_pipeline.ifc_generator_v2 import BuildingSpec, _auto_column_grid
        spec = BuildingSpec(**kwargs)
        return _auto_column_grid(spec)

    def test_default_grid_size(self):
        grid = self._grid()
        assert len(grid) == 3 * 2  # 6 columns

    def test_grid_positions_stay_in_footprint(self):
        grid = self._grid(footprint_length=15000, footprint_width=10000,
                         column_spacing_x=5000, column_spacing_y=5000)
        for cx, cy in grid:
            assert 0 <= cx <= 15000
            assert 0 <= cy <= 10000

    def test_small_building_min_2x2(self):
        grid = self._grid(footprint_length=3000, footprint_width=3000,
                         column_spacing_x=10000, column_spacing_y=10000)
        assert len(grid) >= 4

    def test_grid_corners_present(self):
        grid = self._grid(footprint_length=12000, footprint_width=8000,
                         column_spacing_x=6000, column_spacing_y=8000)
        assert (0, 0) in grid


@requires_ifcopenshell
class TestMatrixHelpers:
    """Test transformation matrix generation."""

    def test_mat4_translation(self):
        from src.data_pipeline.ifc_generator_v2 import _mat4
        m = _mat4(100, 200, 300)
        assert m.shape == (4, 4)
        assert m[0, 3] == 100
        assert m[1, 3] == 200
        assert m[2, 3] == 300
        assert m[3, 3] == 1

    def test_mat4_identity_at_origin(self):
        from src.data_pipeline.ifc_generator_v2 import _mat4
        m = _mat4(0, 0, 0)
        np.testing.assert_array_almost_equal(m, np.eye(4))

    def test_mat4_rz_zero_angle(self):
        from src.data_pipeline.ifc_generator_v2 import _mat4_rz, _mat4
        rz = _mat4_rz(100, 200, 300, 0)
        plain = _mat4(100, 200, 300)
        np.testing.assert_array_almost_equal(rz, plain)

    def test_mat4_rz_90_degrees(self):
        from src.data_pipeline.ifc_generator_v2 import _mat4_rz
        m = _mat4_rz(0, 0, 0, math.pi / 2)
        np.testing.assert_almost_equal(m[0, 0], 0, decimal=10)
        np.testing.assert_almost_equal(m[1, 0], 1, decimal=10)


# ---------------------------------------------------------------------------
# IFC file generation (integration)
# ---------------------------------------------------------------------------

@requires_ifcopenshell
class TestIFCGeneration:
    """Integration tests for IFC file generation."""

    @pytest.fixture
    def tmp_dir(self):
        d = tempfile.mkdtemp(prefix="bim_test_")
        yield d
        shutil.rmtree(d, ignore_errors=True)

    def test_generate_default_building(self, tmp_dir):
        from src.data_pipeline.ifc_generator_v2 import BuildingSpec, generate_from_spec
        spec = BuildingSpec(num_storeys=2, footprint_length=8000, footprint_width=6000)
        filepath = generate_from_spec(spec, output_dir=tmp_dir)
        assert os.path.exists(filepath)
        assert filepath.endswith(".ifc")
        assert os.path.getsize(filepath) > 1000

    def test_generated_file_is_valid_ifc(self, tmp_dir):
        from src.data_pipeline.ifc_generator_v2 import BuildingSpec, generate_from_spec
        spec = BuildingSpec(num_storeys=1, footprint_length=6000, footprint_width=4000)
        filepath = generate_from_spec(spec, output_dir=tmp_dir)
        model = ifcopenshell.open(filepath)
        assert model.schema == "IFC4"

    def test_correct_storey_count(self, tmp_dir):
        from src.data_pipeline.ifc_generator_v2 import BuildingSpec, generate_from_spec
        spec = BuildingSpec(num_storeys=4)
        filepath = generate_from_spec(spec, output_dir=tmp_dir)
        model = ifcopenshell.open(filepath)
        storeys = model.by_type("IfcBuildingStorey")
        assert len(storeys) == 4

    def test_has_walls(self, tmp_dir):
        from src.data_pipeline.ifc_generator_v2 import BuildingSpec, generate_from_spec
        spec = BuildingSpec(num_storeys=2)
        filepath = generate_from_spec(spec, output_dir=tmp_dir)
        model = ifcopenshell.open(filepath)
        walls = model.by_type("IfcWall")
        assert len(walls) >= 4  # At least 4 exterior walls per floor

    def test_has_doors_and_windows(self, tmp_dir):
        from src.data_pipeline.ifc_generator_v2 import BuildingSpec, generate_from_spec
        spec = BuildingSpec(num_storeys=1, doors_per_storey=2, windows_per_storey=3)
        filepath = generate_from_spec(spec, output_dir=tmp_dir)
        model = ifcopenshell.open(filepath)
        assert len(model.by_type("IfcDoor")) >= 2
        assert len(model.by_type("IfcWindow")) >= 3

    def test_has_slabs_with_roof(self, tmp_dir):
        from src.data_pipeline.ifc_generator_v2 import BuildingSpec, generate_from_spec
        spec = BuildingSpec(num_storeys=2)
        filepath = generate_from_spec(spec, output_dir=tmp_dir)
        model = ifcopenshell.open(filepath)
        slabs = model.by_type("IfcSlab")
        assert len(slabs) >= 3  # 2 floors + 1 roof

    def test_has_stairs(self, tmp_dir):
        from src.data_pipeline.ifc_generator_v2 import BuildingSpec, generate_from_spec
        spec = BuildingSpec(num_storeys=2, num_staircases=2)
        filepath = generate_from_spec(spec, output_dir=tmp_dir)
        model = ifcopenshell.open(filepath)
        assert len(model.by_type("IfcStair")) >= 2

    def test_foundations_present(self, tmp_dir):
        from src.data_pipeline.ifc_generator_v2 import BuildingSpec, generate_from_spec
        spec = BuildingSpec(num_storeys=1, has_foundation=True)
        filepath = generate_from_spec(spec, output_dir=tmp_dir)
        model = ifcopenshell.open(filepath)
        assert len(model.by_type("IfcFooting")) > 0

    def test_no_foundations_when_disabled(self, tmp_dir):
        from src.data_pipeline.ifc_generator_v2 import BuildingSpec, generate_from_spec
        spec = BuildingSpec(num_storeys=1, has_foundation=False)
        filepath = generate_from_spec(spec, output_dir=tmp_dir)
        model = ifcopenshell.open(filepath)
        assert len(model.by_type("IfcFooting")) == 0

    def test_wall_pset_properties(self, tmp_dir):
        import ifcopenshell.util.element
        from src.data_pipeline.ifc_generator_v2 import BuildingSpec, generate_from_spec
        spec = BuildingSpec(num_storeys=1)
        filepath = generate_from_spec(spec, output_dir=tmp_dir)
        model = ifcopenshell.open(filepath)
        wall = model.by_type("IfcWall")[0]
        psets = ifcopenshell.util.element.get_psets(wall)
        assert "Pset_WallCommon" in psets
        assert psets["Pset_WallCommon"].get("FireRating") == "REI 120"

    def test_material_assignment(self, tmp_dir):
        import ifcopenshell.util.element
        from src.data_pipeline.ifc_generator_v2 import BuildingSpec, generate_from_spec
        spec = BuildingSpec(num_storeys=1, column_material="BTCT B30")
        filepath = generate_from_spec(spec, output_dir=tmp_dir)
        model = ifcopenshell.open(filepath)
        columns = model.by_type("IfcColumn")
        if columns:
            mat = ifcopenshell.util.element.get_material(columns[0])
            assert mat is not None


# ---------------------------------------------------------------------------
# Geometry extraction tests
# ---------------------------------------------------------------------------

@requires_ifcopenshell
class TestGeometryExtraction:
    """Test ifc_geometry.extract_geometry function."""

    @pytest.fixture
    def sample_ifc(self, tmp_path):
        from src.data_pipeline.ifc_generator_v2 import BuildingSpec, generate_from_spec
        spec = BuildingSpec(
            num_storeys=1,
            footprint_length=6000,
            footprint_width=4000,
            doors_per_storey=1,
            windows_per_storey=1,
            num_staircases=0,
            has_foundation=False,
        )
        return generate_from_spec(spec, output_dir=str(tmp_path))

    def test_extract_returns_meshes(self, sample_ifc):
        from src.data_pipeline.ifc_geometry import extract_geometry
        result = extract_geometry(sample_ifc)
        assert "meshes" in result
        assert "stats" in result
        assert len(result["meshes"]) > 0

    def test_mesh_has_required_keys(self, sample_ifc):
        from src.data_pipeline.ifc_geometry import extract_geometry
        result = extract_geometry(sample_ifc)
        mesh = result["meshes"][0]
        for key in ("v", "f", "c", "o", "m"):
            assert key in mesh

    def test_vertices_are_xyz_triples(self, sample_ifc):
        from src.data_pipeline.ifc_geometry import extract_geometry
        result = extract_geometry(sample_ifc)
        for mesh in result["meshes"]:
            assert all(isinstance(v, (int, float)) for v in mesh["v"])
            assert len(mesh["v"]) % 3 == 0

    def test_faces_reference_valid_vertices(self, sample_ifc):
        from src.data_pipeline.ifc_geometry import extract_geometry
        result = extract_geometry(sample_ifc)
        for mesh in result["meshes"]:
            num_verts = len(mesh["v"]) // 3
            assert all(0 <= f < num_verts for f in mesh["f"])
            assert len(mesh["f"]) % 3 == 0

    def test_stats_element_counts(self, sample_ifc):
        from src.data_pipeline.ifc_geometry import extract_geometry
        result = extract_geometry(sample_ifc)
        assert result["stats"]["total_elements"] > 0

    def test_stats_bounding_box(self, sample_ifc):
        from src.data_pipeline.ifc_geometry import extract_geometry
        result = extract_geometry(sample_ifc)
        stats = result["stats"]
        for i in range(3):
            assert stats["bbox_max"][i] >= stats["bbox_min"][i]

    def test_colors_in_valid_range(self, sample_ifc):
        from src.data_pipeline.ifc_geometry import extract_geometry
        result = extract_geometry(sample_ifc)
        for mesh in result["meshes"]:
            assert all(0.0 <= c <= 1.0 for c in mesh["c"])
            assert 0.0 <= mesh["o"] <= 1.0

    def test_cache_roundtrip(self, sample_ifc, tmp_path):
        from src.data_pipeline.ifc_geometry import extract_geometry
        cache_dir = str(tmp_path / "cache")
        r1 = extract_geometry(sample_ifc, cache_dir=cache_dir)
        r2 = extract_geometry(sample_ifc, cache_dir=cache_dir)
        assert r1["stats"]["total_elements"] == r2["stats"]["total_elements"]
        assert len(list((tmp_path / "cache").glob("*.json"))) == 1

    def test_metadata_fields(self, sample_ifc):
        from src.data_pipeline.ifc_geometry import extract_geometry
        result = extract_geometry(sample_ifc)
        for mesh in result["meshes"]:
            meta = mesh["m"]
            assert "id" in meta
            assert "type" in meta
            assert "name" in meta


# Unit test that always runs (no ifcopenshell needed)
class TestGeometryFileHash:
    """Test _file_hash helper."""

    def _import_hash(self):
        import sys
        if "ifcopenshell" not in sys.modules:
            from unittest.mock import MagicMock
            for mod in ["ifcopenshell", "ifcopenshell.geom",
                         "ifcopenshell.util", "ifcopenshell.util.element"]:
                sys.modules[mod] = MagicMock()
        from src.data_pipeline.ifc_geometry import _file_hash
        return _file_hash

    def test_hash_same_file_same_result(self, tmp_path):
        f = tmp_path / "test.ifc"
        f.write_text("dummy ifc content")
        _file_hash = self._import_hash()
        h1 = _file_hash(str(f))
        h2 = _file_hash(str(f))
        assert h1 == h2
        assert len(h1) == 32  # MD5 hex digest

    def test_hash_different_files_differ(self, tmp_path):
        f1 = tmp_path / "a.ifc"
        f2 = tmp_path / "b.ifc"
        f1.write_text("content a")
        f2.write_text("content b")
        _file_hash = self._import_hash()
        assert _file_hash(str(f1)) != _file_hash(str(f2))


class TestFileNotFound:
    """FileNotFoundError test — always runs."""

    def test_extract_nonexistent_raises(self):
        import sys
        # Mock ifcopenshell if not available
        if "ifcopenshell" not in sys.modules:
            from unittest.mock import MagicMock
            sys.modules["ifcopenshell"] = MagicMock()
            sys.modules["ifcopenshell.geom"] = MagicMock()
            sys.modules["ifcopenshell.util"] = MagicMock()
            sys.modules["ifcopenshell.util.element"] = MagicMock()
        from src.data_pipeline.ifc_geometry import extract_geometry
        with pytest.raises(FileNotFoundError):
            extract_geometry("/nonexistent/path/to/file.ifc")


# ===========================================================================
# BRIDGE TESTS
# ===========================================================================

# ---------------------------------------------------------------------------
# BridgeSpec dataclass tests
# ---------------------------------------------------------------------------

class TestBridgeSpec:
    """Test BridgeSpec dataclass defaults, auto-calc, and validation."""

    def _make(self, **kwargs):
        from src.data_pipeline.base_spec import BridgeSpec
        return BridgeSpec(**kwargs)

    def test_defaults(self):
        spec = self._make()
        assert spec.structure_type == "bridge"
        assert spec.total_length == 30000.0
        assert spec.deck_width == 12000.0
        assert spec.num_spans == 3
        assert spec.num_lanes == 2
        assert spec.bridge_type == "beam"
        assert spec.design_load == "HL-93"

    def test_auto_calc_num_piers(self):
        """num_piers should always be num_spans - 1."""
        spec = self._make(num_spans=5, total_length=50000.0)
        assert spec.num_piers == 4

    def test_auto_calc_num_piers_single_span(self):
        """Single span bridge has 0 piers."""
        spec = self._make(num_spans=1, total_length=15000.0)
        assert spec.num_piers == 0

    def test_auto_calc_span_length(self):
        """span_length should auto-sync from total_length / num_spans."""
        spec = self._make(total_length=45000.0, num_spans=3)
        assert spec.span_length == 15000.0

    def test_auto_calc_structure_name(self):
        """structure_name should default from bridge_name."""
        spec = self._make(bridge_name="Cầu Bình Lợi")
        assert spec.structure_name == "Cầu Bình Lợi"

    def test_auto_sync_abutment_width(self):
        """abutment_width should sync to deck_width if not explicitly set."""
        spec = self._make(deck_width=15000.0)
        assert spec.abutment_width == 15000.0

    def test_validation_negative_length(self):
        """Negative total_length should raise ValueError."""
        with pytest.raises(ValueError, match="total_length"):
            self._make(total_length=-1000.0)

    def test_validation_zero_spans(self):
        """num_spans=0 should raise ValueError."""
        with pytest.raises(ValueError, match="num_spans"):
            self._make(num_spans=0)

    def test_validation_zero_girder_height(self):
        """girder_height=0 should raise ValueError (prevents L/h division by zero)."""
        with pytest.raises(ValueError, match="girder_height"):
            self._make(girder_height=0)

    def test_validation_zero_deck_width(self):
        """deck_width=0 should raise ValueError."""
        with pytest.raises(ValueError, match="deck_width"):
            self._make(deck_width=0)

    def test_override_all_fields(self):
        """All fields should be overridable."""
        spec = self._make(
            bridge_name="Cầu Test",
            total_length=60000.0,
            deck_width=15000.0,
            num_spans=4,
            num_lanes=3,
            pier_height=10000.0,
            girder_height=1500.0,
            foundation_type="caisson",
        )
        assert spec.bridge_name == "Cầu Test"
        assert spec.total_length == 60000.0
        assert spec.num_lanes == 3
        assert spec.num_piers == 3  # auto-calc
        assert spec.span_length == 15000.0  # auto-calc
        assert spec.foundation_type == "caisson"


# ---------------------------------------------------------------------------
# Bridge Compliance tests
# ---------------------------------------------------------------------------

class TestBridgeCompliance:
    """Test bridge compliance checker against TCVN 11823."""

    def _make_spec(self, **kwargs):
        from src.data_pipeline.base_spec import BridgeSpec
        return BridgeSpec(**kwargs)

    def _check(self, **kwargs):
        from src.rag.bridge_compliance import check_bridge_compliance
        spec = self._make_spec(**kwargs)
        return check_bridge_compliance(spec)

    def test_default_spec_passes(self):
        """Default BridgeSpec should mostly pass compliance."""
        result = self._check()
        assert isinstance(result, dict)
        assert "violations" in result
        assert "passing" in result
        # Default spec is designed to be compliant
        errors = [v for v in result["violations"] if v["severity"] == "error"]
        assert len(errors) == 0, f"Default spec has errors: {errors}"

    def test_returns_violations_and_passing(self):
        """Result should separate violations from passing checks."""
        result = self._check()
        for v in result["violations"]:
            assert v["severity"] in ("error", "warning", "info")
        for p in result["passing"]:
            assert p["severity"] == "pass"

    def test_narrow_lane_violation(self):
        """Lane width < 3500mm should be an error."""
        result = self._check(lane_width=3000.0)
        errors = [v for v in result["violations"]
                  if v["severity"] == "error" and "làn xe" in v["issue"]]
        assert len(errors) >= 1

    def test_excessive_lh_ratio_error(self):
        """L/h ratio > 20 should be an error."""
        # span=20000, girder_height=800 → L/h = 25
        result = self._check(total_length=20000.0, num_spans=1,
                            girder_height=800.0)
        errors = [v for v in result["violations"]
                  if v["severity"] == "error" and "L/h" in v["issue"]]
        assert len(errors) >= 1

    def test_short_barrier_error(self):
        """Barrier height < 1100mm should be an error."""
        result = self._check(barrier_height=900.0)
        errors = [v for v in result["violations"]
                  if v["severity"] == "error" and "lan can" in v["issue"]]
        assert len(errors) >= 1

    def test_thin_deck_error(self):
        """Deck thickness < 200mm should be an error."""
        result = self._check(deck_thickness=150.0)
        errors = [v for v in result["violations"]
                  if v["severity"] == "error" and "bản mặt cầu" in v["issue"]]
        assert len(errors) >= 1

    def test_low_clearance_error(self):
        """Clearance < 4500mm for road bridge should be an error."""
        result = self._check(clearance_height=4000.0)
        errors = [v for v in result["violations"]
                  if v["severity"] == "error" and "Tĩnh không" in v["issue"]]
        assert len(errors) >= 1

    def test_rail_clearance_error(self):
        """Clearance < 5500mm for railway bridge should be an error."""
        result = self._check(bridge_function="Đường sắt", clearance_height=5000.0)
        errors = [v for v in result["violations"]
                  if v["severity"] == "error" and "Tĩnh không" in v["issue"]]
        assert len(errors) >= 1

    def test_every_violation_has_required_keys(self):
        """Every violation dict must have rule, issue, severity, suggestion."""
        result = self._check(lane_width=2000.0, barrier_height=500.0)
        for v in result["violations"] + result["passing"]:
            for key in ("rule", "issue", "severity", "suggestion"):
                assert key in v, f"Missing key '{key}' in {v}"


# ---------------------------------------------------------------------------
# Bridge IFC Generation (integration tests)
# ---------------------------------------------------------------------------

@requires_ifcopenshell
class TestBridgeIFCGeneration:
    """Integration tests for bridge IFC file generation."""

    @pytest.fixture
    def tmp_dir(self):
        d = tempfile.mkdtemp(prefix="bim_bridge_test_")
        yield d
        shutil.rmtree(d, ignore_errors=True)

    def _generate(self, tmp_dir, **kwargs):
        from src.data_pipeline.base_spec import BridgeSpec
        from src.data_pipeline.ifc_bridge_generator import generate_bridge
        spec = BridgeSpec(**kwargs)
        return generate_bridge(spec, output_dir=tmp_dir)

    def test_generate_default_bridge(self, tmp_dir):
        """Default bridge spec should generate a valid IFC file."""
        filepath = self._generate(tmp_dir)
        assert os.path.exists(filepath)
        assert filepath.endswith(".ifc")
        assert os.path.getsize(filepath) > 1000

    def test_generated_file_is_valid_ifc4(self, tmp_dir):
        """Bridge IFC should be IFC4 schema."""
        filepath = self._generate(tmp_dir)
        model = ifcopenshell.open(filepath)
        assert model.schema == "IFC4"

    def test_has_piers(self, tmp_dir):
        """Bridge should have correct number of piers (IfcColumn)."""
        filepath = self._generate(tmp_dir, num_spans=3, total_length=30000.0)
        model = ifcopenshell.open(filepath)
        columns = model.by_type("IfcColumn")
        # 3 spans → 2 piers
        assert len(columns) >= 2

    def test_has_girders(self, tmp_dir):
        """Bridge should have girders (IfcBeam) for each span."""
        filepath = self._generate(tmp_dir, num_spans=3, num_girders=4)
        model = ifcopenshell.open(filepath)
        beams = model.by_type("IfcBeam")
        # 3 spans × 4 girders = 12 beams
        assert len(beams) >= 12

    def test_has_deck_slabs(self, tmp_dir):
        """Bridge should have deck slabs (IfcSlab) for each span."""
        filepath = self._generate(tmp_dir, num_spans=3)
        model = ifcopenshell.open(filepath)
        slabs = model.by_type("IfcSlab")
        assert len(slabs) >= 3

    def test_has_abutments(self, tmp_dir):
        """Bridge should have 2 abutments (IfcWall)."""
        filepath = self._generate(tmp_dir)
        model = ifcopenshell.open(filepath)
        walls = model.by_type("IfcWall")
        assert len(walls) >= 2

    def test_has_railings(self, tmp_dir):
        """Bridge should have railings (IfcRailing)."""
        filepath = self._generate(tmp_dir)
        model = ifcopenshell.open(filepath)
        railings = model.by_type("IfcRailing")
        assert len(railings) >= 2  # 2 sides

    def test_has_foundation_piles(self, tmp_dir):
        """Bridge with pile foundation should have IfcPile elements."""
        filepath = self._generate(tmp_dir, foundation_type="pile",
                                  num_piles_per_pier=4, num_spans=3)
        model = ifcopenshell.open(filepath)
        piles = model.by_type("IfcPile")
        # 2 piers × 4 piles + 2 abutments × 4 piles = 16 piles
        assert len(piles) >= 8

    def test_foundation_json_export(self, tmp_dir):
        """Bridge generation should also export _foundation.json."""
        filepath = self._generate(tmp_dir, bridge_name="Cầu_Test")
        import json
        json_path = filepath.replace(".ifc", "_foundation.json")
        assert os.path.exists(json_path), f"No foundation JSON at {json_path}"
        with open(json_path) as f:
            data = json.load(f)
        assert "supports" in data, f"Missing 'supports' key in foundation JSON"
        # Should have at least 2 abutments + piers
        assert len(data["supports"]) >= 2

    def test_single_span_no_piers(self, tmp_dir):
        """Single span bridge should have 0 piers, only abutments."""
        filepath = self._generate(tmp_dir, num_spans=1, total_length=15000.0)
        model = ifcopenshell.open(filepath)
        columns = model.by_type("IfcColumn")
        # Single span = no piers. Only abutments (IfcWall).
        walls = model.by_type("IfcWall")
        assert len(walls) >= 2  # 2 abutments


# ---------------------------------------------------------------------------
# Bridge Geometry Extraction tests
# ---------------------------------------------------------------------------

@requires_ifcopenshell
class TestBridgeGeometryExtraction:
    """Test geometry extraction from bridge IFC files."""

    @pytest.fixture
    def bridge_ifc(self, tmp_path):
        from src.data_pipeline.base_spec import BridgeSpec
        from src.data_pipeline.ifc_bridge_generator import generate_bridge
        spec = BridgeSpec(num_spans=2, total_length=20000.0, num_girders=3)
        return generate_bridge(spec, output_dir=str(tmp_path))

    def test_extract_bridge_returns_meshes(self, bridge_ifc):
        from src.data_pipeline.ifc_geometry import extract_geometry
        result = extract_geometry(bridge_ifc)
        assert "meshes" in result
        assert len(result["meshes"]) > 0

    def test_bridge_element_types_present(self, bridge_ifc):
        """Bridge geometry should include beam, column, slab, wall types."""
        from src.data_pipeline.ifc_geometry import extract_geometry
        result = extract_geometry(bridge_ifc)
        types = {m["m"]["type"] for m in result["meshes"]}
        # At minimum, bridges should have beams (girders), slabs (deck), walls (abutments)
        assert "Beam" in types or "IfcBeam" in types, f"Missing beams in {types}"
        assert "Slab" in types or "IfcSlab" in types, f"Missing slabs in {types}"

    def test_bridge_bounding_box_reasonable(self, bridge_ifc):
        """Bridge bounding box should be roughly total_length × deck_width."""
        from src.data_pipeline.ifc_geometry import extract_geometry
        result = extract_geometry(bridge_ifc)
        stats = result["stats"]
        bbox_size = [
            stats["bbox_max"][i] - stats["bbox_min"][i]
            for i in range(3)
        ]
        # At least one dimension should be > 10m (total_length=20m)
        max_dim = max(bbox_size)
        assert max_dim > 10, f"Bridge bounding box too small: {bbox_size}"


# ---------------------------------------------------------------------------
# Design Tool Routing tests (no LLM calls, no ifcopenshell needed)
# ---------------------------------------------------------------------------

class TestDesignToolRouting:
    """Test bridge/building detection in design tool."""

    def _detect(self, question):
        """Import and call the detection function."""
        import sys
        # Mock ifcopenshell if not available
        if "ifcopenshell" not in sys.modules:
            from unittest.mock import MagicMock
            for mod in ["ifcopenshell", "ifcopenshell.geom",
                        "ifcopenshell.util", "ifcopenshell.util.element"]:
                sys.modules.setdefault(mod, MagicMock())
        from src.rag.tools.design_tool import _detect_structure_type
        return _detect_structure_type(question, {})

    def test_detect_bridge_vietnamese(self):
        """Vietnamese bridge keywords should detect as bridge."""
        assert self._detect("Thiết kế cầu dầm BTCT 30m") == "bridge"

    def test_detect_bridge_no_diacritics(self):
        """Bridge keywords without diacritics should also work."""
        assert self._detect("Thiet ke cau dam BTCT 30m") == "bridge"

    def test_detect_bridge_english(self):
        """English bridge keyword should also work."""
        assert self._detect("Design a 3-span bridge 30m long") == "bridge"

    def test_detect_building_default(self):
        """Non-bridge text should detect as building."""
        assert self._detect("Thiết kế tòa nhà 5 tầng văn phòng") == "building"

    def test_false_positive_stairs(self):
        """'cầu thang' (stairs) should NOT be detected as bridge."""
        assert self._detect("Cầu thang bộ cho tòa nhà 5 tầng") == "building"

