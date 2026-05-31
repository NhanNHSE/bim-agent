"""Generate a sample IFC file for testing.

Creates a simple 3-storey office building with:
- 3 storeys (Tầng 1, Tầng 2, Tầng 3)
- Walls, columns, slabs per storey
- Doors and windows
- Spaces (rooms)
- Materials assigned
"""

import os
import sys
import json
from datetime import datetime


def generate_sample_ifc(output_path: str = "data/ifc/sample_building.ifc"):
    """Generate a minimal but realistic IFC 2x3 file."""

    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # IFC 2x3 format — text-based STEP file
    timestamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    entity_id = 0

    def next_id():
        nonlocal entity_id
        entity_id += 1
        return entity_id

    lines = []
    lines.append("ISO-10303-21;")
    lines.append("HEADER;")
    lines.append(f"FILE_DESCRIPTION(('ViewDefinition [CoordinationView]'),'2;1');")
    lines.append(f"FILE_NAME('{os.path.basename(output_path)}','{timestamp}',('BIM AI Agent'),('BIM AI'),'ifcopenshell','BIM AI Agent','');")
    lines.append("FILE_SCHEMA(('IFC2X3'));")
    lines.append("ENDSEC;")
    lines.append("DATA;")

    # Owner/Application
    person_id = next_id()
    lines.append(f"#{person_id}=IFCPERSON($,$,'BIM Agent',$,$,$,$,$);")
    org_id = next_id()
    lines.append(f"#{org_id}=IFCORGANIZATION($,'BIM AI Corp',$,$,$);")
    person_org_id = next_id()
    lines.append(f"#{person_org_id}=IFCPERSONANDORGANIZATION(#{person_id},#{org_id},$);")
    app_id = next_id()
    lines.append(f"#{app_id}=IFCAPPLICATION(#{org_id},'1.0','BIM AI Agent','BIM_AI');")
    owner_id = next_id()
    lines.append(f"#{owner_id}=IFCOWNERHISTORY(#{person_org_id},#{app_id},$,.NOCHANGE.,$,$,$,0);")

    # Units
    len_unit = next_id()
    lines.append(f"#{len_unit}=IFCSIUNIT(*,.LENGTHUNIT.,.MILLI.,.METRE.);")
    area_unit = next_id()
    lines.append(f"#{area_unit}=IFCSIUNIT(*,.AREAUNIT.,$,.SQUARE_METRE.);")
    vol_unit = next_id()
    lines.append(f"#{vol_unit}=IFCSIUNIT(*,.VOLUMEUNIT.,$,.CUBIC_METRE.);")
    angle_unit = next_id()
    lines.append(f"#{angle_unit}=IFCSIUNIT(*,.PLANEANGLEUNIT.,$,.RADIAN.);")
    units_id = next_id()
    lines.append(f"#{units_id}=IFCUNITASSIGNMENT((#{len_unit},#{area_unit},#{vol_unit},#{angle_unit}));")

    # Geometric context
    origin_id = next_id()
    lines.append(f"#{origin_id}=IFCCARTESIANPOINT((0.,0.,0.));")
    dir_z = next_id()
    lines.append(f"#{dir_z}=IFCDIRECTION((0.,0.,1.));")
    dir_x = next_id()
    lines.append(f"#{dir_x}=IFCDIRECTION((1.,0.,0.));")
    axis_id = next_id()
    lines.append(f"#{axis_id}=IFCAXIS2PLACEMENT3D(#{origin_id},#{dir_z},#{dir_x});")
    ctx_id = next_id()
    lines.append(f"#{ctx_id}=IFCGEOMETRICREPRESENTATIONCONTEXT($,'Model',3,1.0E-05,#{axis_id},$);")

    # Project
    project_id = next_id()
    lines.append(f"#{project_id}=IFCPROJECT('{_guid()}',#{owner_id},'Van Phong ABC','Toa nha van phong 3 tang',$,$,$,(#{ctx_id}),#{units_id});")

    # Site
    site_placement = _make_placement(lines, next_id, origin_id, dir_z, dir_x)
    site_id = next_id()
    lines.append(f"#{site_id}=IFCSITE('{_guid()}',#{owner_id},'Khu dat A','Dia chi: 123 Nguyen Van Linh, Da Nang',$,#{site_placement},$,$,.ELEMENT.,$,$,$,$,$);")

    # Building
    bldg_placement = _make_placement(lines, next_id, origin_id, dir_z, dir_x)
    bldg_id = next_id()
    lines.append(f"#{bldg_id}=IFCBUILDING('{_guid()}',#{owner_id},'Toa nha VP-ABC','Van phong lam viec 3 tang',$,#{bldg_placement},$,$,.ELEMENT.,$,$,$);")

    # Aggregate: Project → Site → Building
    rel1 = next_id()
    lines.append(f"#{rel1}=IFCRELAGGREGATES('{_guid()}',#{owner_id},$,$,#{project_id},(#{site_id}));")
    rel2 = next_id()
    lines.append(f"#{rel2}=IFCRELAGGREGATES('{_guid()}',#{owner_id},$,$,#{site_id},(#{bldg_id}));")

    # Materials
    mat_concrete = next_id()
    lines.append(f"#{mat_concrete}=IFCMATERIAL('Be tong cot thep B25');")
    mat_brick = next_id()
    lines.append(f"#{mat_brick}=IFCMATERIAL('Gach ong 200mm');")
    mat_glass = next_id()
    lines.append(f"#{mat_glass}=IFCMATERIAL('Kinh cuong luc 10mm');")
    mat_steel = next_id()
    lines.append(f"#{mat_steel}=IFCMATERIAL('Thep hinh I-beam');")

    # Create 3 storeys
    storey_ids = []
    storey_data = [
        ("Tang 1", 0.0),
        ("Tang 2", 3500.0),
        ("Tang 3", 7000.0),
    ]

    all_elements = []  # (storey_id, element_id) pairs

    for storey_name, elevation in storey_data:
        storey_placement = _make_placement(lines, next_id, origin_id, dir_z, dir_x)
        storey_id = next_id()
        lines.append(
            f"#{storey_id}=IFCBUILDINGSTOREY('{_guid()}',#{owner_id},'{storey_name}',"
            f"'Cao do {elevation/1000:.1f}m',$,#{storey_placement},$,$,.ELEMENT.,{elevation});"
        )
        storey_ids.append(storey_id)

        elements_on_storey = []

        # Walls (4 exterior walls per storey)
        wall_data = [
            (f"Tuong Bac {storey_name}", 0, 0, 12000, 200, 3200),
            (f"Tuong Nam {storey_name}", 0, 8000, 12000, 200, 3200),
            (f"Tuong Dong {storey_name}", 12000, 0, 200, 8000, 3200),
            (f"Tuong Tay {storey_name}", 0, 0, 200, 8000, 3200),
        ]
        for wname, wx, wy, wl, ww, wh in wall_data:
            wall_id = _create_wall(lines, next_id, owner_id, ctx_id, origin_id, dir_z, dir_x,
                                   wname, wx, wy, wl, ww, wh, mat_brick)
            elements_on_storey.append(wall_id)

        # Interior wall
        int_wall = _create_wall(lines, next_id, owner_id, ctx_id, origin_id, dir_z, dir_x,
                                f"Tuong ngan {storey_name}", 6000, 0, 200, 8000, 3200, mat_brick)
        elements_on_storey.append(int_wall)

        # Columns (4 corners + 2 middle)
        col_positions = [(0, 0), (12000, 0), (0, 8000), (12000, 8000), (6000, 0), (6000, 8000)]
        for i, (cx, cy) in enumerate(col_positions):
            col_id = _create_column(lines, next_id, owner_id, ctx_id, origin_id, dir_z, dir_x,
                                    f"Cot C{i+1} {storey_name}", cx, cy, 400, 400, 3500, mat_concrete)
            elements_on_storey.append(col_id)

        # Slab
        slab_id = _create_slab(lines, next_id, owner_id, ctx_id, origin_id, dir_z, dir_x,
                               f"San {storey_name}", 0, 0, 12000, 8000, 200, mat_concrete)
        elements_on_storey.append(slab_id)

        # Doors (2 per storey)
        for i in range(2):
            door_id = _create_door(lines, next_id, owner_id, ctx_id, origin_id, dir_z, dir_x,
                                   f"Cua di D{i+1} {storey_name}", 2000 + i * 4000, 0, 900, 2100)
            elements_on_storey.append(door_id)

        # Windows (3 per storey)
        for i in range(3):
            win_id = _create_window(lines, next_id, owner_id, ctx_id, origin_id, dir_z, dir_x,
                                    f"Cua so W{i+1} {storey_name}", 1500 + i * 3500, 8000, 1200, 1500, mat_glass)
            elements_on_storey.append(win_id)

        # Spaces
        space1 = _create_space(lines, next_id, owner_id, ctx_id, origin_id, dir_z, dir_x,
                               f"Phong lam viec {storey_name}", "Van phong", 0, 0, 6000, 8000, 3200)
        elements_on_storey.append(space1)
        space2 = _create_space(lines, next_id, owner_id, ctx_id, origin_id, dir_z, dir_x,
                               f"Phong hop {storey_name}", "Phong hop", 6200, 0, 5800, 8000, 3200)
        elements_on_storey.append(space2)

        # Spatial containment
        rel_contain = next_id()
        el_refs = ",".join(f"#{eid}" for eid in elements_on_storey)
        lines.append(
            f"#{rel_contain}=IFCRELCONTAINEDINSPATIALSTRUCTURE('{_guid()}',#{owner_id},$,$,"
            f"({el_refs}),#{storey_id});"
        )

    # Building → Storeys
    storey_refs = ",".join(f"#{sid}" for sid in storey_ids)
    rel3 = next_id()
    lines.append(f"#{rel3}=IFCRELAGGREGATES('{_guid()}',#{owner_id},$,$,#{bldg_id},({storey_refs}));")

    lines.append("ENDSEC;")
    lines.append("END-ISO-10303-21;")

    content = "\n".join(lines)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"✅ Created sample IFC: {output_path}")
    print(f"   Project: Van Phong ABC")
    print(f"   Storeys: {len(storey_data)}")
    print(f"   Total entities: {entity_id}")

    return output_path


# ===== Helper functions =====

_guid_counter = 0

def _guid():
    """Generate a simple IFC GlobalId (22 char base64)."""
    global _guid_counter
    _guid_counter += 1
    import hashlib
    h = hashlib.md5(f"bim_sample_{_guid_counter}".encode()).hexdigest()[:22]
    # IFC GlobalId uses base64-like chars
    return "".join(c if c.isalnum() else chr(65 + ord(c) % 26) for c in h)


def _make_placement(lines, next_id, origin_id, dir_z, dir_x):
    """Create an IfcLocalPlacement."""
    axis_id = next_id()
    lines.append(f"#{axis_id}=IFCAXIS2PLACEMENT3D(#{origin_id},#{dir_z},#{dir_x});")
    placement_id = next_id()
    lines.append(f"#{placement_id}=IFCLOCALPLACEMENT($,#{axis_id});")
    return placement_id


def _create_extruded_solid(lines, next_id, ctx_id, origin_id, dir_z, dir_x, x, y, length, width, height):
    """Create a simple extruded rectangular solid."""
    # Profile points
    p1 = next_id()
    lines.append(f"#{p1}=IFCCARTESIANPOINT(({float(x)},{float(y)}));")
    p2 = next_id()
    lines.append(f"#{p2}=IFCCARTESIANPOINT(({float(x+length)},{float(y)}));")
    p3 = next_id()
    lines.append(f"#{p3}=IFCCARTESIANPOINT(({float(x+length)},{float(y+width)}));")
    p4 = next_id()
    lines.append(f"#{p4}=IFCCARTESIANPOINT(({float(x)},{float(y+width)}));")

    polyline = next_id()
    lines.append(f"#{polyline}=IFCPOLYLINE((#{p1},#{p2},#{p3},#{p4},#{p1}));")

    profile = next_id()
    lines.append(f"#{profile}=IFCARBITRARYCLOSEDPROFILEDEF(.AREA.,$,#{polyline});")

    dir_up = next_id()
    lines.append(f"#{dir_up}=IFCDIRECTION((0.,0.,1.));")

    solid = next_id()
    lines.append(f"#{solid}=IFCEXTRUDEDAREASOLID(#{profile},$,#{dir_up},{float(height)});")

    shape_rep = next_id()
    lines.append(f"#{shape_rep}=IFCSHAPEREPRESENTATION(#{ctx_id},'Body','SweptSolid',(#{solid}));")

    prod_shape = next_id()
    lines.append(f"#{prod_shape}=IFCPRODUCTDEFINITIONSHAPE($,$,(#{shape_rep}));")

    return prod_shape


def _create_wall(lines, next_id, owner_id, ctx_id, origin_id, dir_z, dir_x,
                 name, x, y, length, width, height, material_id):
    """Create an IfcWall."""
    placement = _make_placement(lines, next_id, origin_id, dir_z, dir_x)
    shape = _create_extruded_solid(lines, next_id, ctx_id, origin_id, dir_z, dir_x, x, y, length, width, height)

    wall_id = next_id()
    lines.append(
        f"#{wall_id}=IFCWALLSTANDARDCASE('{_guid()}',#{owner_id},'{name}',"
        f"'Tuong xay gach',$,#{placement},#{shape},$);"
    )

    # Material association
    rel_mat = next_id()
    lines.append(f"#{rel_mat}=IFCRELASSOCIATESMATERIAL('{_guid()}',#{owner_id},$,$,(#{wall_id}),#{material_id});")

    # Property: IsExternal, FireRating
    _add_property_set(lines, next_id, owner_id, wall_id, "Pset_WallCommon", {
        "IsExternal": (".BOOLEAN.", ".T."),
        "FireRating": (".STRING.", "'REI 120'"),
    })

    return wall_id


def _create_column(lines, next_id, owner_id, ctx_id, origin_id, dir_z, dir_x,
                   name, x, y, width, depth, height, material_id):
    """Create an IfcColumn."""
    placement = _make_placement(lines, next_id, origin_id, dir_z, dir_x)
    shape = _create_extruded_solid(lines, next_id, ctx_id, origin_id, dir_z, dir_x,
                                   x - width/2, y - depth/2, width, depth, height)

    col_id = next_id()
    lines.append(
        f"#{col_id}=IFCCOLUMN('{_guid()}',#{owner_id},'{name}',"
        f"'Cot BTCT 400x400',$,#{placement},#{shape},$);"
    )

    rel_mat = next_id()
    lines.append(f"#{rel_mat}=IFCRELASSOCIATESMATERIAL('{_guid()}',#{owner_id},$,$,(#{col_id}),#{material_id});")

    return col_id


def _create_slab(lines, next_id, owner_id, ctx_id, origin_id, dir_z, dir_x,
                 name, x, y, length, width, thickness, material_id):
    """Create an IfcSlab."""
    placement = _make_placement(lines, next_id, origin_id, dir_z, dir_x)
    shape = _create_extruded_solid(lines, next_id, ctx_id, origin_id, dir_z, dir_x,
                                   x, y, length, width, thickness)

    slab_id = next_id()
    lines.append(
        f"#{slab_id}=IFCSLAB('{_guid()}',#{owner_id},'{name}',"
        f"'San BTCT day {thickness}mm',$,#{placement},#{shape},$,.FLOOR.);"
    )

    rel_mat = next_id()
    lines.append(f"#{rel_mat}=IFCRELASSOCIATESMATERIAL('{_guid()}',#{owner_id},$,$,(#{slab_id}),#{material_id});")

    return slab_id


def _create_door(lines, next_id, owner_id, ctx_id, origin_id, dir_z, dir_x,
                 name, x, y, width, height):
    """Create an IfcDoor."""
    placement = _make_placement(lines, next_id, origin_id, dir_z, dir_x)
    shape = _create_extruded_solid(lines, next_id, ctx_id, origin_id, dir_z, dir_x,
                                   x, y, width, 50, height)

    door_id = next_id()
    lines.append(
        f"#{door_id}=IFCDOOR('{_guid()}',#{owner_id},'{name}',"
        f"'Cua di go',$,#{placement},#{shape},$,{float(height)},{float(width)});"
    )

    _add_property_set(lines, next_id, owner_id, door_id, "Pset_DoorCommon", {
        "FireRating": (".STRING.", "'EI 60'"),
        "IsExternal": (".BOOLEAN.", ".F."),
    })

    return door_id


def _create_window(lines, next_id, owner_id, ctx_id, origin_id, dir_z, dir_x,
                   name, x, y, width, height, material_id):
    """Create an IfcWindow."""
    placement = _make_placement(lines, next_id, origin_id, dir_z, dir_x)
    shape = _create_extruded_solid(lines, next_id, ctx_id, origin_id, dir_z, dir_x,
                                   x, y, width, 30, height)

    win_id = next_id()
    lines.append(
        f"#{win_id}=IFCWINDOW('{_guid()}',#{owner_id},'{name}',"
        f"'Cua so kinh cuong luc',$,#{placement},#{shape},$,{float(height)},{float(width)});"
    )

    rel_mat = next_id()
    lines.append(f"#{rel_mat}=IFCRELASSOCIATESMATERIAL('{_guid()}',#{owner_id},$,$,(#{win_id}),#{material_id});")

    return win_id


def _create_space(lines, next_id, owner_id, ctx_id, origin_id, dir_z, dir_x,
                  name, long_name, x, y, length, width, height):
    """Create an IfcSpace."""
    placement = _make_placement(lines, next_id, origin_id, dir_z, dir_x)
    shape = _create_extruded_solid(lines, next_id, ctx_id, origin_id, dir_z, dir_x,
                                   x, y, length, width, height)

    space_id = next_id()
    lines.append(
        f"#{space_id}=IFCSPACE('{_guid()}',#{owner_id},'{name}',"
        f"'Khong gian su dung',$,#{placement},#{shape},$,.ELEMENT.,.INTERNAL.,{float(height)});"
    )

    # Add area quantity
    area = (length / 1000.0) * (width / 1000.0)
    q_area = next_id()
    lines.append(f"#{q_area}=IFCQUANTITYAREA('NetFloorArea','Dien tich san',$,{area},$);")
    q_set = next_id()
    lines.append(f"#{q_set}=IFCELEMENTQUANTITY('{_guid()}',#{owner_id},'Qto_SpaceBaseQuantities',$,$,(#{q_area}));")
    rel_q = next_id()
    lines.append(f"#{rel_q}=IFCRELDEFINESBYPROPERTIES('{_guid()}',#{owner_id},$,$,(#{space_id}),#{q_set});")

    return space_id


def _add_property_set(lines, next_id, owner_id, element_id, pset_name, properties):
    """Add a property set to an element."""
    prop_ids = []
    for prop_name, (prop_type, prop_value) in properties.items():
        val_id = next_id()
        if prop_type == ".BOOLEAN.":
            lines.append(f"#{val_id}=IFCPROPERTYSINGLEVALUE('{prop_name}',$,IFCBOOLEAN({prop_value}),$);")
        else:
            lines.append(f"#{val_id}=IFCPROPERTYSINGLEVALUE('{prop_name}',$,IFCLABEL({prop_value}),$);")
        prop_ids.append(val_id)

    prop_refs = ",".join(f"#{pid}" for pid in prop_ids)
    pset_id = next_id()
    lines.append(f"#{pset_id}=IFCPROPERTYSET('{_guid()}',#{owner_id},'{pset_name}',$,({prop_refs}));")

    rel_id = next_id()
    lines.append(f"#{rel_id}=IFCRELDEFINESBYPROPERTIES('{_guid()}',#{owner_id},$,$,(#{element_id}),#{pset_id});")


if __name__ == "__main__":
    output = sys.argv[1] if len(sys.argv) > 1 else "data/ifc/sample_building.ifc"
    generate_sample_ifc(output)
