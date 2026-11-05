"""Extra unit tests for generator unit conversion helpers and baseline report sync."""

import json
import math
from pathlib import Path

import numpy as np

from scripts.check_models import build_report
from src.data_pipeline.ifc_bridge_generator import _m as bridge_m, _mat4 as bridge_mat4, _mat4_x
from src.data_pipeline.ifc_generator_v2 import _m as bldg_m, _mat4_beam

BACKEND = Path(__file__).resolve().parents[2]


def test_mm_to_m_helpers():
    assert bldg_m(3500.0) == 3.5
    assert bridge_m(30000.0) == 30.0
    m = bridge_mat4(1000.0, 2000.0, 3000.0)
    assert (m[0, 3], m[1, 3], m[2, 3]) == (1.0, 2.0, 3.0)


def test_horizontal_extrusion_matrices_are_orthonormal():
    for angle in (0.0, math.pi / 2):
        mb = _mat4_beam(1.0, 2.0, 3.0, angle)
        r = mb[:3, :3]
        np.testing.assert_allclose(r.T @ r, np.eye(3), atol=1e-12)
        assert np.isclose(np.linalg.det(r), 1.0)
    mx = _mat4_x(1000.0, 2000.0, 3000.0)
    rx = mx[:3, :3]
    np.testing.assert_allclose(rx.T @ rx, np.eye(3), atol=1e-12)
    assert np.isclose(np.linalg.det(rx), 1.0)


def test_baseline_clashes_sync():
    cases = json.loads((BACKEND / "eval" / "model_cases.json").read_text(encoding="utf-8"))
    baseline = json.loads((BACKEND / "eval" / "model_baseline.json").read_text(encoding="utf-8"))
    report = build_report(cases)
    assert report == baseline, f"EXACT_REPORT={json.dumps(report)}"
