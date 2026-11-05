"""Extra unit tests for src/model_checks and scripts/check_models.py."""

import json
import pytest
import ifcopenshell

from scripts.check_models import build_report, compare, main
from src.model_checks import (
     check_clashes,
    check_columns_on_grid,
    check_wall_connections,
)


def test_single_wall_needs_no_connection():
    model = ifcopenshell.file(schema="IFC4")
    model.create_entity("IfcWall", GlobalId=ifcopenshell.guid.new(), Name="SingleWall")
    assert check_wall_connections(model) == []


def test_no_columns_returns_empty_without_grid():
    model = ifcopenshell.file(schema="IFC4")
    assert check_columns_on_grid(model) == []


def test_clashes_with_fewer_than_two_elements():
    model = ifcopenshell.file(schema="IFC4")
    assert check_clashes(model) == []


def test_unknown_generator_raises():
    with pytest.raises(ValueError, match="Unsupported generator"):
        build_report({"cases": [{"id": "bad", "generator": "unknown_gen", "spec": {}}]})


def test_main_missing_baseline_returns_1(tmp_path):
    cases = tmp_path / "cases.json"
    cases.write_text(
        json.dumps({"cases": [{"id": "c1", "generator": "building_v2", "spec": {"num_storeys": 1}}]}),
        encoding="utf-8",
    )
    missing_baseline = tmp_path / "does_not_exist.json"
    assert main(["--cases", str(cases), "--baseline", str(missing_baseline)]) == 1
