"""Quick smoke test for IFC Generator v2."""
import os

from src.data_pipeline.ifc_generator_v2 import generate_from_spec, BuildingSpec


def main():
    spec = BuildingSpec(
        project_name="Test Phase 3",
        building_name="Toa nha VP 5 tang",
        building_function="Van phong",
        num_storeys=5,
        storey_height=3500,
        footprint_length=14000,
        footprint_width=10000,
        column_size=400,
        column_spacing_x=7000,
        column_spacing_y=10000,
        slab_thickness=200,
        wall_thickness=200,
        beam_height=400,
        beam_width=200,
        doors_per_storey=2,
        windows_per_storey=4,
        num_staircases=2,
        has_foundation=True,
        has_roof_railing=True,
    )
    filepath = generate_from_spec(spec, output_dir="/app/data/ifc")
    print(f"\\n=== IFC v2 Generated ===")
    print(f"File: {filepath}")
    print(f"Size: {os.path.getsize(filepath):,} bytes")

    # Validate with ifcopenshell
    import ifcopenshell
    model = ifcopenshell.open(filepath)
    print(f"Schema: {model.schema}")
    
    types = {}
    for e in model.by_type("IfcProduct"):
        t = e.is_a()
        types[t] = types.get(t, 0) + 1
    
    print(f"\\n--- Elements ---")
    for t, c in sorted(types.items()):
        print(f"  {t}: {c}")
    
    # Check materials
    mats = model.by_type("IfcMaterial")
    print(f"\\n--- Materials ({len(mats)}) ---")
    for m in mats:
        print(f"  {m.Name}")
    
    # Check layer sets
    layer_sets = model.by_type("IfcMaterialLayerSet")
    print(f"\\n--- Material Layer Sets ({len(layer_sets)}) ---")
    for ls in layer_sets:
        layers = ls.MaterialLayers
        print(f"  {ls.LayerSetName}: {len(layers)} layers")
        for l in layers:
            print(f"    - {l.Name or 'N/A'}: {l.LayerThickness}mm ({l.Material.Name})")
    
    # Check psets
    psets = model.by_type("IfcPropertySet")
    print(f"\\n--- Property Sets ({len(psets)}) ---")
    pset_names = {}
    for ps in psets:
        pset_names[ps.Name] = pset_names.get(ps.Name, 0) + 1
    for name, count in sorted(pset_names.items()):
        print(f"  {name}: {count}")
    
    print(f"\\n✅ IFC v2 Generator test PASSED!")

if __name__ == "__main__":
    main()
