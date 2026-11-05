"""Acceptance tests for task 015 (automatic model checks + baseline ratchet). LOCKED.

Expected values were verified against a reference implementation on the fixture in ifc_fixtures.py.
"""

import json
from pathlib import Path

import pytest

from tests.unit.ifc_fixtures import build_house

REPO_ROOT = Path(__file__).resolve().parents[3]
BACKEND = Path(__file__).resolve().parents[2]

CHECK_NAMES = ["schema", "required_classes", "openings", "wall_connections",
               "columns_on_grid", "spaces", "extent", "clashes"]
LOD200 = ["IfcFooting", "IfcColumn", "IfcBeam", "IfcSlab", "IfcWall", "IfcDoor", "IfcWindow",
          "IfcStair", "IfcRailing", "IfcRoof", "IfcSpace"]


def _names(model, issues):
    return sorted(model.by_guid(i.element).Name for i in issues)


@pytest.fixture(scope="module")
def good():
    return build_house()


# ── interface ─────────────────────────────────────────────────────────────────

def test_public_interface():
    from src.model_checks import CHECKS, LOD200_REQUIRED, Issue, run_all
    assert callable(run_all)
    assert list(CHECKS) == CHECK_NAMES
    assert list(LOD200_REQUIRED) == LOD200
    i = Issue(check="openings", message="x", element=None)
    assert i.other is None
    with pytest.raises(Exception):
        i.check = "y"  # frozen dataclass


def test_good_model_has_no_issues(good):
    from src.model_checks import run_all
    result = run_all(good)
    assert list(result) == CHECK_NAMES
    assert {k: v for k, v in result.items() if v} == {}


# ── one variant per property ──────────────────────────────────────────────────

def test_schema_invalid_entity():
    from src.model_checks import check_schema
    issues = check_schema(build_house(invalid_proxy=True))
    assert len(issues) >= 1
    assert all(i.check == "schema" for i in issues)


def test_required_classes_missing():
    from src.model_checks import check_required_classes
    issues = check_required_classes(build_house(no_stair_railing_roof=True))
    assert len(issues) == 3
    for cls in ("IfcStair", "IfcRailing", "IfcRoof"):
        assert any(cls in i.message for i in issues), cls
    assert all(i.element is None and i.check == "required_classes" for i in issues)


def test_required_classes_custom_list(good):
    from src.model_checks import check_required_classes
    assert check_required_classes(good, required=["IfcWall"]) == []
    issues = check_required_classes(good, required=["IfcCovering", "IfcWall"])
    assert len(issues) == 1 and "IfcCovering" in issues[0].message


def test_openings_missing():
    from src.model_checks import check_openings
    m = build_house(no_openings=True)
    issues = check_openings(m)
    assert _names(m, issues) == ["D1", "WIN1"]
    assert all(i.check == "openings" for i in issues)


def test_wall_connections_missing():
    from src.model_checks import check_wall_connections
    m = build_house(no_connection=True)
    assert _names(m, check_wall_connections(m)) == ["W1", "W2"]


def test_column_off_grid():
    from src.model_checks import check_columns_on_grid
    m = build_house(column_off_grid=True)
    issues = check_columns_on_grid(m)
    assert _names(m, issues) == ["C2"]
    # 100 mm off: inside a 150 mm tolerance it is accepted
    assert check_columns_on_grid(m, tolerance_mm=150.0) == []


def test_no_grid_with_columns():
    from src.model_checks import check_columns_on_grid
    issues = check_columns_on_grid(build_house(no_grid=True))
    assert len(issues) == 1
    assert issues[0].element is None and "IfcGrid" in issues[0].message


def test_storey_without_space():
    from src.model_checks import check_spaces
    m = build_house(no_space_t2=True)
    assert _names(m, check_spaces(m)) == ["T2"]


def test_extent_catches_kilometre_placement():
    from src.model_checks import check_extent
    m = build_house(far_stair=True)
    assert _names(m, check_extent(m)) == ["ST1"]
    assert check_extent(m, max_m=10000.0) == []


def test_clash_detected_once_per_pair():
    from src.model_checks import check_clashes
    m = build_house(stair_into_wall=True)
    issues = check_clashes(m)
    assert len(issues) == 1
    pair = sorted([m.by_guid(issues[0].element).Name, m.by_guid(issues[0].other).Name])
    assert pair == ["ST1", "W1"]
    assert "ST1" in issues[0].message or "IfcStair" in issues[0].message


def test_door_window_without_opening_clash_with_wall():
    from src.model_checks import check_clashes
    m = build_house(no_openings=True)
    pairs = sorted(sorted([m.by_guid(i.element).Name, m.by_guid(i.other).Name]) for i in check_clashes(m))
    assert pairs == [["D1", "W1"], ["W2", "WIN1"]]


def test_hosted_door_and_connected_walls_are_not_clashes(good):
    from src.model_checks import check_clashes
    assert check_clashes(good) == []


def test_each_variant_only_breaks_its_own_checks():
    from src.model_checks import run_all
    expected = {
        "no_openings": {"openings", "clashes"},
        "no_connection": {"wall_connections"},
        "column_off_grid": {"columns_on_grid"},
        "no_grid": {"columns_on_grid"},
        "no_stair_railing_roof": {"required_classes"},
        "no_space_t2": {"spaces"},
        "far_stair": {"extent"},
        "stair_into_wall": {"clashes"},
        "invalid_proxy": {"schema"},
    }
    for variant, checks in expected.items():
        result = run_all(build_house(**{variant: True}))
        assert {k for k, v in result.items() if v} == checks, variant


# ── baseline ratchet script ───────────────────────────────────────────────────

def test_compare_detects_regressions_only():
    from scripts.check_models import compare
    base = {"cases": {"a": {"x": 3, "y": 0}}}
    assert compare({"cases": {"a": {"x": 2, "y": 0}}}, base) == []
    assert compare({"cases": {"a": {"x": 4, "y": 0}}}, base) == ["a/x: 3 -> 4"]
    assert compare({"cases": {"a": {"x": 3, "y": 0}, "b": {"x": 0}}}, base) == ["b: không có trong baseline"]


def test_main_update_then_compare(tmp_path):
    from scripts.check_models import main
    cases = tmp_path / "cases.json"
    cases.write_text(json.dumps({"cases": [{"id": "nho", "generator": "building_v2",
                                            "spec": {"num_storeys": 1}}]}), encoding="utf-8")
    baseline = tmp_path / "baseline.json"
    out = tmp_path / "report.json"
    args = ["--cases", str(cases), "--baseline", str(baseline), "--out", str(out)]
    assert main(args + ["--update-baseline"]) == 0
    data = json.loads(baseline.read_text(encoding="utf-8"))
    assert list(data["cases"]["nho"]) == CHECK_NAMES
    assert main(args) == 0
    assert json.loads(out.read_text(encoding="utf-8")) == data
    # make the baseline stricter than reality -> regression -> exit 1
    worst = max(CHECK_NAMES, key=lambda c: data["cases"]["nho"][c])
    assert data["cases"]["nho"][worst] > 0, "1-storey production model is expected to have issues"
    data["cases"]["nho"][worst] -= 1
    baseline.write_text(json.dumps(data), encoding="utf-8")
    assert main(args) == 1


@pytest.mark.skipif(not (BACKEND / "eval").exists(), reason="eval/ không có trong image backend; chạy ở job Unit Tests")
def test_committed_cases_and_baseline_match():
    from scripts.check_models import compare, build_report
    cases = json.loads((BACKEND / "eval" / "model_cases.json").read_text(encoding="utf-8"))
    ids = [c["id"] for c in cases["cases"]]
    assert ids == ["default_3t", "nha_pho_4t", "van_phong_6t"]
    baseline = json.loads((BACKEND / "eval" / "model_baseline.json").read_text(encoding="utf-8"))
    report = build_report(cases)
    assert report == baseline, "baseline must be regenerated with --update-baseline"
    assert compare(report, baseline) == []


@pytest.mark.skipif(not (REPO_ROOT / ".github").exists(), reason="CI workflow chỉ có trên checkout repo")
def test_ci_runs_model_checks():
    ci = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "python scripts/check_models.py" in ci
