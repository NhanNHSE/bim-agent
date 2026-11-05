"""Run automatic IFC model checks across evaluation cases and enforce baseline ratchet."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import tempfile

import ifcopenshell

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from src.data_pipeline.ifc_generator_v2 import BuildingSpec, generate_from_spec
from src.model_checks import CHECKS, run_all


def build_report(cases: dict) -> dict:
    """cases = nội dung model_cases.json -> {"cases": {case_id: {check_name: số issue}}}, giữ thứ tự case và CHECKS."""
    report_cases: dict[str, dict[str, int]] = {}
    with tempfile.TemporaryDirectory(prefix="bim_model_checks_") as tmp_root:
        for idx, case in enumerate(cases.get("cases", [])):
            case_id = case["id"]
            generator = case.get("generator")
            if generator != "building_v2":
                raise ValueError(f"Unsupported generator '{generator}' for case '{case_id}'")
            case_dir = Path(tmp_root) / f"{idx}_{case_id}"
            case_dir.mkdir(parents=True, exist_ok=True)
            spec = BuildingSpec(**case.get("spec", {}))
            ifc_path = generate_from_spec(spec, output_dir=str(case_dir))
            model = ifcopenshell.open(ifc_path)
            issues_by_check = run_all(model)
            report_cases[case_id] = {name: len(issues_by_check[name]) for name in CHECKS}
    return {"cases": report_cases}


def compare(report: dict, baseline: dict) -> list[str]:
    """Danh sách hồi quy: f"{case}/{check}: {old} -> {new}" khi new > old; f"{case}: không có trong baseline" khi case mới."""
    base_cases = baseline.get("cases", {})
    regressions: list[str] = []
    for case_id, checks in report.get("cases", {}).items():
        if case_id not in base_cases:
            regressions.append(f"{case_id}: không có trong baseline")
            continue
        base_checks = base_cases[case_id]
        for check_name, new_count in checks.items():
            old_count = base_checks.get(check_name)
            if old_count is None or new_count > old_count:
                regressions.append(f"{case_id}/{check_name}: {old_count} -> {new_count}")
    return regressions


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _format_markdown_table(report: dict) -> str:
    check_names = list(CHECKS)
    header = "| Case | " + " | ".join(check_names) + " |"
    sep = "|---|" + "|".join("---:" for _ in check_names) + "|"
    rows = [header, sep]
    for case_id, counts in report.get("cases", {}).items():
        vals = " | ".join(str(counts.get(c, 0)) for c in check_names)
        rows.append(f"| {case_id} | {vals} |")
    return "\n".join(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check generated IFC models against quality baseline.")
    parser.add_argument("--cases", default="eval/model_cases.json", help="Path to model_cases.json")
    parser.add_argument("--baseline", default="eval/model_baseline.json", help="Path to model_baseline.json")
    parser.add_argument("--out", default=None, help="Optional path to write report JSON")
    parser.add_argument("--update-baseline", action="store_true", help="Write report to baseline and exit 0")
    args = parser.parse_args(argv)

    cases_path = Path(args.cases)
    baseline_path = Path(args.baseline)

    cases_data = json.loads(cases_path.read_text(encoding="utf-8"))
    report = build_report(cases_data)

    if args.out:
        _write_json(Path(args.out), report)

    if args.update_baseline:
        _write_json(baseline_path, report)
        return 0

    print(_format_markdown_table(report))

    if not baseline_path.exists():
        print(f"Baseline file not found: {baseline_path}")
        return 1

    baseline_data = json.loads(baseline_path.read_text(encoding="utf-8"))
    regressions = compare(report, baseline_data)
    if regressions:
        for line in regressions:
            print(line)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
