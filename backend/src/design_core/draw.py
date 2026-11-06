"""Pillow-based 2D floor-plan PNG renderer for Layout."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from src.design_core.layout import Layout

_KIND_COLORS: dict[str, tuple[int, int, int]] = {
    "san": (212, 238, 199),
    "ban_cong": (205, 235, 214),
    "giat_phoi": (222, 240, 226),
    "san_thuong": (212, 238, 199),
    "khach": (253, 232, 195),
    "bep_an": (252, 213, 181),
    "ngu": (214, 228, 248),
    "tho": (235, 218, 245),
    "wc": (197, 232, 242),
    "sanh": (245, 242, 216),
    "hanh_lang": (240, 238, 225),
    "kho": (226, 220, 210),
    "gieng_troi": (224, 247, 250),
    "de_xe": (228, 230, 235),
    "stair": (185, 190, 198),
}
_DEFAULT_ROOM_COLOR = (232, 235, 240)
_BG_COLOR = (250, 251, 253)
_BORDER_COLOR = (25, 30, 38)
_TEXT_COLOR = (20, 24, 32)
_DOOR_COLOR = (220, 38, 38)


@lru_cache(maxsize=16)
def load_font(size: int) -> ImageFont.FreeTypeFont:
    """Load bundled DejaVuSans TrueType font at the requested pixel size."""
    return ImageFont.truetype(str(Path(__file__).parent / "fonts" / "DejaVuSans.ttf"), size)


def draw_layout(layout: Layout, out_path: str | Path, px_per_m: int = 40) -> None:
    """Render all floors of `layout` side-by-side into an RGB PNG image."""
    x0_mm, y0_mm, x1_mm, y1_mm = layout.buildable_mm
    min_y_mm = min([y0_mm] + [r.y_mm for fl in layout.floors for r in fl.rooms])
    max_y_mm = max([y1_mm] + [r.y_mm + r.d_mm for fl in layout.floors for r in fl.rooms])
    build_w_m = max((x1_mm - x0_mm) / 1000.0, 0.1)
    build_d_m = max((max_y_mm - min_y_mm) / 1000.0, 0.1)

    panel_w = round(build_w_m * px_per_m)
    panel_h = round(build_d_m * px_per_m)

    margin_x = 32
    panel_gap = 32
    header_h = 64
    footer_h = 28

    num_floors = max(len(layout.floors), 1)
    total_panels_w = num_floors * panel_w + (num_floors - 1) * panel_gap
    canvas_w = max(400, total_panels_w + 2 * margin_x)
    canvas_h = header_h + panel_h + footer_h
    start_x = (canvas_w - total_panels_w) // 2

    img = Image.new("RGB", (canvas_w, canvas_h), _BG_COLOR)
    draw = ImageDraw.Draw(img)
    title_font = load_font(16)
    room_font = load_font(12)

    draw.text((margin_x, 12), f"{layout.program_name} ({layout.typology})", fill=_TEXT_COLOR, font=title_font)

    def to_px(px0: int, py0: int, xm: int, ym: int) -> tuple[int, int]:
        # Front (y0_mm) is towards the bottom of the panel; max_y_mm is at py0.
        sx = px0 + round((xm - x0_mm) * px_per_m / 1000.0)
        sy = py0 + round((max_y_mm - ym) * px_per_m / 1000.0)
        return sx, sy

    door_half_mm = 450  # 0.9 m door centered on shared segment

    for idx, floor in enumerate(layout.floors):
        px0 = start_x + idx * (panel_w + panel_gap)
        py0 = header_h

        draw.text((px0, py0 - 24), floor.name, fill=_TEXT_COLOR, font=title_font)

        for room in floor.rooms:
            rx0, ry1 = to_px(px0, py0, room.x_mm, room.y_mm)
            rx1, ry0 = to_px(px0, py0, room.x_mm + room.w_mm, room.y_mm + room.d_mm)
            box = (min(rx0, rx1), min(ry0, ry1), max(rx0, rx1), max(ry0, ry1))
            fill_color = _KIND_COLORS.get(room.kind, _DEFAULT_ROOM_COLOR)
            draw.rectangle(box, fill=fill_color, outline=_BORDER_COLOR, width=2)

            area_m2 = (room.w_mm * room.d_mm) / 1e6
            label = f"{room.id}\n{area_m2:.1f} m²"
            cx = (box[0] + box[2]) // 2
            cy = (box[1] + box[3]) // 2
            draw.multiline_text(
                (max(box[0] + 4, cx - 22), max(box[1] + 4, cy - 12)),
                label,
                fill=_TEXT_COLOR,
                font=room_font,
                align="center",
            )

        for conn in floor.connections:
            mx = (conn.x0_mm + conn.x1_mm) // 2
            my = (conn.y0_mm + conn.y1_mm) // 2
            if conn.x0_mm == conn.x1_mm:
                dy0 = max(conn.y0_mm, my - door_half_mm)
                dy1 = min(conn.y1_mm, my + door_half_mm)
                p0 = to_px(px0, py0, mx, dy0)
                p1 = to_px(px0, py0, mx, dy1)
            else:
                dx0 = max(conn.x0_mm, mx - door_half_mm)
                dx1 = min(conn.x1_mm, mx + door_half_mm)
                p0 = to_px(px0, py0, dx0, my)
                p1 = to_px(px0, py0, dx1, my)
            draw.line([p0, p1], fill=_DOOR_COLOR, width=4)

        bx0, by1 = to_px(px0, py0, x0_mm, y0_mm)
        bx1, by0 = to_px(px0, py0, x1_mm, y1_mm)
        draw.rectangle((bx0, by0, bx1, by1), outline=_BORDER_COLOR, width=2)

    out_file = Path(out_path)
    if out_file.parent:
        out_file.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(out_file), format="PNG")
