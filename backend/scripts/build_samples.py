"""Build complete LOD 200 IFC4 models and PNG renders for all sample programs of a typology."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from scripts.render_model import render
from src.data_pipeline.ifc_geometry import extract_geometry
from src.design_core.building import build_ifc
from src.design_core.layout import LayoutInfeasible, solve_layout
from src.design_core.typologies import load_samples
from src.model_checks import run_all


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Dựng mô hình IFC4 LOD 200 hoàn chỉnh cho các chương trình mẫu và xuất IFC + PNG."
    )
    parser.add_argument(
        "--typology",
        default="nha_pho",
        help="Loại hình công trình (mặc định: nha_pho)",
    )
    parser.add_argument(
        "--out-dir",
        default="../test-results/buildings",
        help="Thư mục đầu ra cho file .ifc và .png",
    )

    args = parser.parse_args(argv)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    samples = load_samples(args.typology)
    all_ok = True

    for prog in samples:
        try:
            layout = solve_layout(prog)
        except LayoutInfeasible as exc:
            print(f"Lỗi [{prog.name}]: {exc}", file=sys.stderr)
            all_ok = False
            continue

        model = build_ifc(layout)
        ifc_path = out_dir / f"{prog.name}.ifc"
        png_path = out_dir / f"{prog.name}.png"
        model.write(str(ifc_path))

        checks = run_all(model)
        counts_str = " ".join(f"{k}={len(v)}" for k, v in checks.items())
        n_elements = len(model.by_type("IfcElement"))
        print(f"{prog.name}: elements={n_elements} {counts_str}")

        if any(checks.values()):
            all_ok = False

        geom = extract_geometry(str(ifc_path))
        render(geom, str(png_path))

    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
