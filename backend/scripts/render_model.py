"""Render an IFC model or geometry JSON to a side-by-side PNG (axonometric + plan view)."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

_HEADER_HEIGHT = 60
_BG_COLOR = (245, 247, 250)
_HEADER_BG = (235, 238, 245)
_HEADER_TEXT = (20, 24, 35)
_COS30 = math.cos(math.pi / 6.0)
_SIN30 = 0.5
_LIGHT = np.array([0.4, 0.3, 0.85], dtype=np.float64)
_LIGHT = _LIGHT / np.linalg.norm(_LIGHT)


def _compute_bbox_m(stats: dict, meshes: list[dict]) -> list[float]:
    bbox_min = stats.get("bbox_min")
    bbox_max = stats.get("bbox_max")
    if (
        isinstance(bbox_min, (list, tuple))
        and isinstance(bbox_max, (list, tuple))
        and len(bbox_min) == 3
        and len(bbox_max) == 3
    ):
        diffs = [float(bbox_max[i]) - float(bbox_min[i]) for i in range(3)]
        if all(math.isfinite(d) for d in diffs):
            return [round(d, 2) for d in diffs]

    all_pts = []
    for m in meshes:
        v = m.get("v", [])
        if len(v) >= 3:
            all_pts.append(np.asarray(v, dtype=np.float64).reshape(-1, 3))
    if not all_pts:
        return [0.0, 0.0, 0.0]
    stacked = np.vstack(all_pts)
    mins = stacked.min(axis=0)
    maxs = stacked.max(axis=0)
    return [round(float(maxs[i] - mins[i]), 2) for i in range(3)]


def _extract_triangles(meshes: list[dict]) -> list[dict]:
    triangles: list[dict] = []
    for mesh in meshes:
        verts_flat = mesh.get("v", [])
        faces_flat = mesh.get("f", [])
        if len(verts_flat) < 9 or len(faces_flat) < 3:
            continue

        verts = np.asarray(verts_flat, dtype=np.float64).reshape(-1, 3)
        faces = np.asarray(faces_flat, dtype=np.int64).reshape(-1, 3)

        raw_c = mesh.get("c", [0.7, 0.7, 0.7])
        c0 = float(raw_c[0]) if len(raw_c) > 0 else 0.7
        c1 = float(raw_c[1]) if len(raw_c) > 1 else 0.7
        c2 = float(raw_c[2]) if len(raw_c) > 2 else 0.7
        if max(c0, c1, c2) > 1.0:
            c0, c1, c2 = c0 / 255.0, c1 / 255.0, c2 / 255.0

        opacity = max(float(mesh.get("o", 1.0)), 0.25)
        alpha = int(round(min(max(opacity, 0.25), 1.0) * 255.0))

        for i0, i1, i2 in faces:
            p0 = verts[i0]
            p1 = verts[i1]
            p2 = verts[i2]
            n = np.cross(p1 - p0, p2 - p0)
            norm_n = float(np.linalg.norm(n))
            if norm_n > 1e-12:
                dot_val = abs(float(np.dot(n / norm_n, _LIGHT)))
            else:
                dot_val = 0.0

            shade = 0.45 + 0.55 * dot_val
            r = int(round(min(max(c0 * shade * 255.0, 0.0), 255.0)))
            g = int(round(min(max(c1 * shade * 255.0, 0.0), 255.0)))
            b = int(round(min(max(c2 * shade * 255.0, 0.0), 255.0)))
            rgba = (r, g, b, alpha)

            cx = float((p0[0] + p1[0] + p2[0]) / 3.0)
            cy = float((p0[1] + p1[1] + p2[1]) / 3.0)
            cz = float((p0[2] + p1[2] + p2[2]) / 3.0)

            iso_pts = [
                ((float(p[0]) - float(p[1])) * _COS30, (float(p[0]) + float(p[1])) * _SIN30 - float(p[2]))
                for p in (p0, p1, p2)
            ]
            plan_pts = [(float(p[0]), -float(p[1])) for p in (p0, p1, p2)]

            tie_key = (
                round(cx, 6),
                round(cy, 6),
                round(cz, 6),
                tuple(round(float(coord), 5) for pt in (p0, p1, p2) for coord in pt),
                rgba,
            )

            triangles.append(
                {
                    "iso_depth": round(cx + cy - 0.1 * cz, 9),
                    "plan_depth": round(cz, 9),
                    "tie_key": tie_key,
                    "iso_pts": iso_pts,
                    "plan_pts": plan_pts,
                    "rgba": rgba,
                }
            )
    return triangles


def _draw_panel(
    draw: ImageDraw.ImageDraw,
    triangles: list[dict],
    pts_key: str,
    depth_key: str,
    panel_box: tuple[int, int, int, int],
) -> None:
    if not triangles:
        return

    px0, py0, pw, ph = panel_box
    us = [pt[0] for tri in triangles for pt in tri[pts_key]]
    vs = [pt[1] for tri in triangles for pt in tri[pts_key]]
    u_min, u_max = min(us), max(us)
    v_min, v_max = min(vs), max(vs)

    du = max(u_max - u_min, 1e-6)
    dv = max(v_max - v_min, 1e-6)
    scale = 0.90 * min(pw / du, ph / dv)
    uc = 0.5 * (u_min + u_max)
    vc = 0.5 * (v_min + v_max)
    cx = px0 + pw * 0.5
    cy = py0 + ph * 0.5

    sorted_tris = sorted(triangles, key=lambda t: (t[depth_key], t["tie_key"]))
    for tri in sorted_tris:
        screen_pts = [
            (cx + (u - uc) * scale, cy + (v - vc) * scale)
            for u, v in tri[pts_key]
        ]
        draw.polygon(screen_pts, fill=tri["rgba"])


def render(geometry: dict, out_path: str, size: tuple[int, int] = (1400, 700)) -> dict:
    """Render geometry dictionary into a PNG with axonometric (left) and plan (right) views."""
    width, height = int(size[0]), int(size[1])
    meshes = geometry.get("meshes", [])
    stats = geometry.get("stats", {})
    bbox_m = _compute_bbox_m(stats, meshes)

    img = Image.new("RGB", (width, height), _BG_COLOR)
    draw = ImageDraw.Draw(img, "RGBA")

    draw.rectangle((0, 0, width, _HEADER_HEIGHT), fill=_HEADER_BG)

    building_name = stats.get("building_name") or "Unknown"
    element_counts = stats.get("element_counts") or {}
    counts_str = ", ".join(f"{k}: {v}" for k, v in sorted(element_counts.items())) or "none"

    font = ImageFont.load_default()
    line1 = (
        f"Building: {building_name}  |  Meshes: {len(meshes)}  |  "
        f"BBox (m): {bbox_m[0]:.2f} x {bbox_m[1]:.2f} x {bbox_m[2]:.2f}"
    )
    line2 = f"Elements: {counts_str}"
    draw.text((16, 10), line1, fill=_HEADER_TEXT, font=font)
    draw.text((16, 32), line2, fill=_HEADER_TEXT, font=font)

    triangles = _extract_triangles(meshes)
    panel_h = max(height - _HEADER_HEIGHT, 1)
    half_w = width // 2

    _draw_panel(
        draw,
        triangles,
        pts_key="iso_pts",
        depth_key="iso_depth",
        panel_box=(0, _HEADER_HEIGHT, half_w, panel_h),
    )
    _draw_panel(
        draw,
        triangles,
        pts_key="plan_pts",
        depth_key="plan_depth",
        panel_box=(half_w, _HEADER_HEIGHT, width - half_w, panel_h),
    )

    out_file = Path(out_path)
    if out_file.parent:
        out_file.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(out_file), format="PNG")

    return {
        "meshes": len(meshes),
        "bbox_m": bbox_m,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Render model IFC hoặc geometry JSON ra ảnh PNG (trục đo + mặt bằng)."
    )
    parser.add_argument("input_path", help="Đường dẫn file .ifc hoặc .json")
    parser.add_argument("out_path", help="Đường dẫn file ảnh .png đầu ra")
    parser.add_argument("--cache-dir", default=None, help="Thư mục cache cho extract_geometry")

    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return 2

    in_path = Path(args.input_path)
    if not in_path.is_file():
        print(f"Lỗi: Không tìm thấy file đầu vào '{args.input_path}'.", file=sys.stderr)
        return 2

    ext = in_path.suffix.lower()
    if ext not in (".ifc", ".json"):
        print(
            f"Lỗi: Định dạng file '{ext}' không được hỗ trợ (chỉ hỗ trợ .ifc hoặc .json).",
            file=sys.stderr,
        )
        return 2

    try:
        if ext == ".ifc":
            from src.data_pipeline.ifc_geometry import extract_geometry

            geometry = extract_geometry(str(in_path), cache_dir=args.cache_dir)
        else:
            with open(in_path, "r", encoding="utf-8") as f:
                geometry = json.load(f)
    except Exception as exc:
        print(f"Lỗi khi đọc dữ liệu hình học: {exc}", file=sys.stderr)
        return 2

    summary = render(geometry, args.out_path)
    print(f"{args.out_path} bbox_m={summary['bbox_m']} meshes={summary['meshes']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
