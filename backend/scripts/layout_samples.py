"""Solve all sample programs for a typology and export JSON + PNG floor plans."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from src.design_core.draw import draw_layout
from src.design_core.layout import LayoutInfeasible, solve_layout
from src.design_core.typologies import load_samples


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Giải mặt bằng cho các chương trình mẫu và xuất JSON + PNG."
    )
    parser.add_argument(
        "--typology",
        default="nha_pho",
        help="Loại hình công trình (mặc định: nha_pho)",
    )
    parser.add_argument(
        "--out-dir",
        default="../test-results/layouts",
        help="Thư mục đầu ra cho file .json và .png",
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

        json_path = out_dir / f"{prog.name}.json"
        png_path = out_dir / f"{prog.name}.png"
        json_path.write_text(layout.model_dump_json(indent=2), encoding="utf-8")
        draw_layout(layout, png_path)
        print(
            f"{prog.name}: status={layout.stats.status} "
            f"objective={layout.stats.objective:.1f} "
            f"time={layout.stats.wall_time_s:.3f}s"
        )

    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
