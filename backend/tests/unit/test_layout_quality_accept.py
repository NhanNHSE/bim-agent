"""Acceptance tests for task 019, round 2: solver quality/speed and Vietnamese text in images. LOCKED.

Round 1 met every hard rule but stopped at the time budget on 2 of 3 samples (FEASIBLE, area off by up to
83 m²: kitchen 58.5 m² instead of 35, living room 14.6 instead of 30) and took ~17 s; images showed "Tầng"
and "m²" as boxes because Pillow's default font has no Vietnamese glyphs.
"""

import inspect
import time
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont

import src.design_core as design_core
from src.design_core.draw import load_font
from src.design_core.layout import solve_layout
from src.design_core.typologies import load_samples

SAMPLES = load_samples("nha_pho")


@pytest.mark.parametrize("prog", SAMPLES, ids=lambda p: p.name)
def test_samples_reach_optimum_quickly(prog):
    t0 = time.perf_counter()
    lay = solve_layout(prog)
    elapsed = time.perf_counter() - t0
    assert lay.stats.status == "OPTIMAL", f"{prog.name}: {lay.stats.status}"
    x0, y0, x1, y1 = lay.buildable_mm
    cells = (x1 - x0) * (y1 - y0) / 10_000 * len(prog.floors)  # objective unit: 0.01 m² cells
    assert lay.stats.objective <= 0.05 * cells, f"{prog.name}: lệch diện tích {lay.stats.objective / 100} m²"
    assert elapsed < 10, f"{prog.name} giải mất {elapsed:.1f} s"


def test_font_is_a_bundled_truetype_font():
    font = load_font(14)
    assert isinstance(font, ImageFont.FreeTypeFont)
    pkg = Path(design_core.__file__).resolve().parent
    assert Path(font.path).resolve().is_relative_to(pkg)
    assert load_font(20).size == 20


def _glyph(font, ch: str) -> bytes:
    img = Image.new("L", (64, 64))
    ImageDraw.Draw(img).text((8, 8), ch, font=font, fill=255)
    return img.tobytes()


@pytest.mark.parametrize("ch", ["ầ", "ữ", "ạ", "Đ", "²"])
def test_font_has_vietnamese_glyphs(ch):
    font = load_font(14)
    missing = _glyph(font, "")  # private-use code point: renders as the "missing glyph" box
    assert _glyph(font, ch) != missing, f"font thiếu ký tự {ch!r}"


def test_images_use_the_bundled_font():
    import scripts.render_model as render_model
    from src.design_core import draw

    for mod in (draw, render_model):
        src = inspect.getsource(mod)
        assert "load_font" in src, mod.__name__
        assert "load_default" not in src, mod.__name__
