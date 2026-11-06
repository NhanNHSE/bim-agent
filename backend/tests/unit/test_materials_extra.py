"""Extra unit tests for src.design_core.materials."""

from __future__ import annotations

import ifcopenshell
import ifcopenshell.api
import ifcopenshell.util.element as ue
import pytest

from src.design_core.materials import (
    ALL_MATERIALS,
    BY_CLASS,
    CONCRETE,
    FLOOR,
    GLASS,
    ROOF,
    STEEL,
    WALL_EXT,
    WALL_INT,
    WOOD,
    assign_building_materials,
    create_material_palette,
    material_for_element,
)

run = ifcopenshell.api.run


def test_material_constants_match_table():
    assert CONCRETE == ("Bê tông cốt thép", (0.70, 0.70, 0.68), 0.0)
    assert FLOOR == ("Sàn bê tông lát gạch men", (0.87, 0.83, 0.76), 0.0)
    assert ROOF == ("Mái bê tông chống thấm", (0.55, 0.57, 0.60), 0.0)
    assert WALL_EXT == ("Tường gạch sơn ngoài", (0.96, 0.94, 0.89), 0.0)
    assert WALL_INT == ("Tường gạch sơn trong", (0.99, 0.98, 0.96), 0.0)
    assert WOOD == ("Gỗ", (0.52, 0.34, 0.20), 0.0)
    assert GLASS == ("Kính", (0.55, 0.75, 0.88), 0.5)
    assert STEEL == ("Thép sơn", (0.22, 0.24, 0.27), 0.0)
    assert len(ALL_MATERIALS) == 8
    assert BY_CLASS["IfcWindow"] == GLASS
    assert BY_CLASS["IfcDoor"] == WOOD


def test_create_palette_and_assign_materials_once_per_model():
    model = ifcopenshell.file(schema="IFC4")
    run("root.create_entity", model, ifc_class="IfcProject", name="Test")
    run("unit.assign_unit", model, length={"is_metric": True, "raw": "MILLIMETERS"})
    ctx = run("context.add_context", model, context_type="Model")
    body = run(
        "context.add_context",
        model,
        context_type="Model",
        context_identifier="Body",
        target_view="MODEL_VIEW",
        parent=ctx,
    )

    w_ext = run("root.create_entity", model, ifc_class="IfcWall", name="W_EXT")
    pset_ext = run("pset.add_pset", model, product=w_ext, name="Pset_WallCommon")
    run("pset.edit_pset", model, pset=pset_ext, properties={"IsExternal": True})

    w_int = run("root.create_entity", model, ifc_class="IfcWall", name="W_INT")
    pset_int = run("pset.add_pset", model, product=w_int, name="Pset_WallCommon")
    run("pset.edit_pset", model, pset=pset_int, properties={"IsExternal": False})

    assert material_for_element(w_ext) == WALL_EXT
    assert material_for_element(w_int) == WALL_INT

    assign_building_materials(model, body)

    # Exactly 8 materials created once per model
    mats = model.by_type("IfcMaterial")
    assert len(mats) == 8
    assert ue.get_material(w_ext).Name == WALL_EXT[0]
    assert ue.get_material(w_int).Name == WALL_INT[0]

    # Rendering styles use IfcSurfaceStyleRendering with finite Transparency
    renderings = model.by_type("IfcSurfaceStyleRendering")
    assert len(renderings) == 8
    by_style_name = {
        s.Name: s.Styles[0]
        for s in model.by_type("IfcSurfaceStyle")
    }
    assert by_style_name["Kính"].Transparency == pytest.approx(0.5)
    assert by_style_name["Gỗ"].Transparency == pytest.approx(0.0)


def test_create_material_palette_returns_all_eight():
    model = ifcopenshell.file(schema="IFC4")
    run("root.create_entity", model, ifc_class="IfcProject", name="Test")
    ctx = run("context.add_context", model, context_type="Model")
    body = run(
        "context.add_context",
        model,
        context_type="Model",
        context_identifier="Body",
        target_view="MODEL_VIEW",
        parent=ctx,
    )
    palette = create_material_palette(model, body)
    assert set(palette) == {m[0] for m in ALL_MATERIALS}
