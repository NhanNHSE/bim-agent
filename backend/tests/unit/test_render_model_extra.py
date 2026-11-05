"""Extra unit tests for scripts/render_model.py."""

from PIL import Image

from scripts.render_model import main, render


def _tri_mesh(z: float, color: list[float], opacity: float = 1.0) -> dict:
    v = [0.0, 0.0, z, 2.0, 0.0, z, 2.0, 2.0, z, 0.0, 2.0, z]
    return {
        "v": v,
        "f": [0, 1, 2, 0, 2, 3],
        "c": color,
        "o": opacity,
        "m": {"id": f"m_{z}", "type": "Slab", "name": f"Slab_{z}"},
    }


def test_custom_size_and_min_opacity(tmp_path):
    geom = {
        "meshes": [_tri_mesh(0.0, [0.2, 0.6, 0.9], opacity=0.05)],
        "stats": {
            "building_name": "CustomSize",
            "bbox_min": [0.0, 0.0, 0.0],
            "bbox_max": [2.0, 2.0, 0.5],
            "element_counts": {"Slab": 1},
        },
    }
    out = tmp_path / "custom.png"
    res = render(geom, str(out), size=(800, 400))
    assert res == {"meshes": 1, "bbox_m": [2.0, 2.0, 0.5]}
    img = Image.open(out)
    assert img.size == (800, 400)


def test_missing_file_prints_vietnamese_stderr(tmp_path, capsys):
    code = main([str(tmp_path / "missing.ifc"), str(tmp_path / "out.png")])
    assert code == 2
    captured = capsys.readouterr()
    assert captured.err.strip() != ""
    assert not (tmp_path / "out.png").exists()
