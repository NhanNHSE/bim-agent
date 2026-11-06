"""Material palette and IFC4 material/surface-style assignment for generated buildings."""

from __future__ import annotations

import ifcopenshell
import ifcopenshell.api
import ifcopenshell.util.element as ue

run = ifcopenshell.api.run

# (Vietnamese IfcMaterial Name, RGB 0-1 tuple, Transparency 0-1)
MaterialSpec = tuple[str, tuple[float, float, float], float]

CONCRETE: MaterialSpec = ("Bê tông cốt thép", (0.70, 0.70, 0.68), 0.0)
FLOOR: MaterialSpec = ("Sàn bê tông lát gạch men", (0.87, 0.83, 0.76), 0.0)
ROOF: MaterialSpec = ("Mái bê tông chống thấm", (0.55, 0.57, 0.60), 0.0)
WALL_EXT: MaterialSpec = ("Tường gạch sơn ngoài", (0.96, 0.94, 0.89), 0.0)
WALL_INT: MaterialSpec = ("Tường gạch sơn trong", (0.99, 0.98, 0.96), 0.0)
WOOD: MaterialSpec = ("Gỗ", (0.52, 0.34, 0.20), 0.0)
GLASS: MaterialSpec = ("Kính", (0.55, 0.75, 0.88), 0.5)
STEEL: MaterialSpec = ("Thép sơn", (0.22, 0.24, 0.27), 0.0)

ALL_MATERIALS: tuple[MaterialSpec, ...] = (
    CONCRETE,
    FLOOR,
    ROOF,
    WALL_EXT,
    WALL_INT,
    WOOD,
    GLASS,
    STEEL,
)

MATERIAL_CATEGORIES: dict[str, str] = {
    CONCRETE[0]: "concrete",
    FLOOR[0]: "concrete",
    ROOF[0]: "concrete",
    WALL_EXT[0]: "brick",
    WALL_INT[0]: "brick",
    WOOD[0]: "wood",
    GLASS[0]: "glass",
    STEEL[0]: "steel",
}

BY_CLASS: dict[str, MaterialSpec] = {
    "IfcColumn": CONCRETE,
    "IfcBeam": CONCRETE,
    "IfcFooting": CONCRETE,
    "IfcStair": CONCRETE,
    "IfcSlab": FLOOR,
    "IfcRoof": ROOF,
    "IfcDoor": WOOD,
    "IfcWindow": GLASS,
    "IfcRailing": STEEL,
}


def material_for_element(el: ifcopenshell.entity_instance) -> MaterialSpec:
    """Return the MaterialSpec for a building element."""
    if el.is_a("IfcWall"):
        ext = (ue.get_pset(el, "Pset_WallCommon") or {}).get("IsExternal")
        return WALL_EXT if ext else WALL_INT
    return BY_CLASS[el.is_a()]


def create_material_palette(
    model: ifcopenshell.file,
    body: ifcopenshell.entity_instance,
) -> dict[str, tuple[ifcopenshell.entity_instance, ifcopenshell.entity_instance]]:
    """Create each IfcMaterial and its IfcSurfaceStyleRendering once per model."""
    palette: dict[str, tuple[ifcopenshell.entity_instance, ifcopenshell.entity_instance]] = {}
    for name, (r, g, b), t in ALL_MATERIALS:
        mat = run(
            "material.add_material",
            model,
            name=name,
            category=MATERIAL_CATEGORIES.get(name),
        )
        style = run("style.add_style", model, name=name)
        run(
            "style.add_surface_style",
            model,
            style=style,
            ifc_class="IfcSurfaceStyleRendering",
            attributes={
                "SurfaceColour": {"Name": None, "Red": float(r), "Green": float(g), "Blue": float(b)},
                "Transparency": float(t),
                "ReflectanceMethod": "NOTDEFINED",
            },
        )
        run("style.assign_material_style", model, material=mat, style=style, context=body)
        palette[name] = (mat, style)
    return palette


def assign_building_materials(
    model: ifcopenshell.file,
    body: ifcopenshell.entity_instance,
) -> None:
    """Assign IfcMaterial and representation surface styles to all non-feature elements."""
    palette = create_material_palette(model, body)
    elements = [e for e in model.by_type("IfcElement") if not e.is_a("IfcFeatureElement")]
    for el in elements:
        name, _, _ = material_for_element(el)
        mat, style = palette[name]
        run("material.assign_material", model, products=[el], material=mat)
        if el.Representation:
            for rep in el.Representation.Representations:
                if rep.RepresentationIdentifier == "Body":
                    run(
                        "style.assign_representation_styles",
                        model,
                        shape_representation=rep,
                        styles=[style],
                    )
