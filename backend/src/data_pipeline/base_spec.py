"""Base specification classes for all structure types.

Provides BaseSpec (shared fields) and BridgeSpec for bridge generation.
BuildingSpec remains in ifc_generator_v2.py for backward compatibility.
"""

import math
from dataclasses import dataclass, fields, is_dataclass
from typing import Any


@dataclass
class BaseSpec:
    """Common fields shared across all structure types."""
    project_name: str = "Dự án mới"
    structure_name: str = "Công trình"
    structure_type: str = "building"  # "building" | "bridge"
    address: str = ""
    architect: str = "BIM AI Agent"


@dataclass
class BridgeSpec(BaseSpec):
    """Full specification for a concrete beam bridge.

    Default values represent a typical 3-span prestressed concrete
    beam bridge commonly found on Vietnamese national highways,
    designed per TCVN 11823:2017 and 22TCN 272-05.

    All dimensions in millimeters (mm).
    """
    structure_type: str = "bridge"
    bridge_name: str = "Cầu mới"
    bridge_type: str = "beam"  # "beam" | "arch" | "cable_stayed" | "suspension"
    bridge_function: str = "Đường bộ"  # "Đường bộ" | "Đường sắt" | "Bộ hành"

    # --- Overall geometry ---
    total_length: float = 30000.0       # mm (30m)
    deck_width: float = 12000.0         # mm (12m — 2 làn xe + 2 lề)
    num_spans: int = 3                  # Số nhịp
    span_length: float = 10000.0        # mm mỗi nhịp (auto = total_length / num_spans)

    # --- Lanes & sidewalks ---
    num_lanes: int = 2
    lane_width: float = 3750.0          # mm (≥3500 per TCVN 11823 §2.5)
    has_sidewalk: bool = True
    sidewalk_width: float = 1500.0      # mm

    # --- Piers (trụ cầu) ---
    num_piers: int = 2                  # = num_spans - 1
    pier_height: float = 8000.0         # mm
    pier_width: float = 1500.0          # mm (along bridge axis)
    pier_depth: float = 2000.0          # mm (transverse)
    pier_material: str = "Bê tông cốt thép B30"

    # --- Abutments (mố cầu) ---
    abutment_height: float = 6000.0     # mm
    abutment_width: float = 12000.0     # mm (= deck_width)
    abutment_depth: float = 3000.0      # mm
    abutment_material: str = "Bê tông cốt thép B30"

    # --- Deck (bản mặt cầu) ---
    deck_thickness: float = 300.0       # mm
    deck_material: str = "Bê tông cốt thép B30"

    # --- Girders (dầm cầu) ---
    girder_type: str = "I"              # "I" | "T" | "box"
    girder_height: float = 1200.0       # mm
    girder_width: float = 600.0         # mm (flange width)
    girder_web_thickness: float = 200.0 # mm
    girder_flange_thickness: float = 150.0  # mm
    num_girders: int = 4                # Số dầm mỗi nhịp
    girder_material: str = "Bê tông dự ứng lực B40"

    # --- Barriers & Railings (lan can, rào chắn) ---
    barrier_height: float = 1100.0      # mm (≥1100 per TCVN 11823 §13.8)
    barrier_post_spacing: float = 2000.0  # mm
    barrier_material: str = "Thép mạ kẽm"

    # --- Bearings (gối cầu) ---
    bearing_type: str = "elastomeric"   # "elastomeric" | "pot" | "spherical"
    bearing_length: float = 400.0       # mm
    bearing_width: float = 300.0        # mm
    bearing_height: float = 100.0       # mm

    # --- Foundation (móng cọc) ---
    foundation_type: str = "pile"       # "pile" | "spread" | "caisson"
    pile_diameter: float = 600.0        # mm
    pile_depth: float = 15000.0         # mm
    num_piles_per_pier: int = 4
    pile_cap_thickness: float = 1500.0  # mm
    pile_material: str = "Bê tông cốt thép B25"

    # --- Design loads ---
    design_load: str = "HL-93"          # TCVN 11823
    clearance_height: float = 4500.0    # mm (tĩnh không, ≥4500 cho đường bộ)

    def __post_init__(self):
        """Auto-calculate derived values and validate inputs."""
        # --- Validation ---
        if self.num_spans < 1:
            raise ValueError(f"num_spans must be ≥ 1, got {self.num_spans}")
        if self.total_length <= 0:
            raise ValueError(f"total_length must be > 0, got {self.total_length}")
        if self.deck_width <= 0:
            raise ValueError(f"deck_width must be > 0, got {self.deck_width}")
        if self.girder_height <= 0:
            raise ValueError(f"girder_height must be > 0, got {self.girder_height}")

        # --- Auto-calculate derived values ---
        # Always sync num_piers from num_spans
        self.num_piers = self.num_spans - 1

        # Sync span_length from total_length / num_spans
        if self.span_length * self.num_spans != self.total_length:
            self.span_length = self.total_length / self.num_spans

        # Sync abutment_width to deck_width if not explicitly set
        if self.abutment_width == 12000.0 and self.deck_width != 12000.0:
            self.abutment_width = self.deck_width

        # Default structure_name from bridge_name
        if not self.structure_name or self.structure_name == "Công trình":
            self.structure_name = self.bridge_name


SPEC_BOUNDS: dict[str, dict[str, tuple[float, float]]] = {
    "building": {
        "num_storeys": (1.0, 40.0),
        "storey_height": (2400.0, 6000.0),
        "footprint_length": (3000.0, 150000.0),
        "footprint_width": (3000.0, 150000.0),
        "wall_thickness": (100.0, 600.0),
        "column_size": (200.0, 1500.0),
        "slab_thickness": (80.0, 500.0),
        "beam_height": (200.0, 1500.0),
        "beam_width": (150.0, 800.0),
        "num_interior_walls_x": (0.0, 20.0),
        "num_interior_walls_y": (0.0, 20.0),
        "doors_per_storey": (0.0, 50.0),
        "windows_per_storey": (0.0, 100.0),
        "num_staircases": (0.0, 10.0),
        "column_spacing_x": (2000.0, 15000.0),
        "column_spacing_y": (2000.0, 15000.0),
        "corridor_width": (900.0, 6000.0),
        "footing_depth": (300.0, 5000.0),
        "railing_height": (900.0, 1500.0),
        "riser_height": (100.0, 200.0),
        "tread_depth": (220.0, 400.0),
        "window_sill_height": (0.0, 1500.0),
    },
    "bridge": {
        "total_length": (6000.0, 500000.0),
        "deck_width": (4000.0, 40000.0),
        "num_spans": (1.0, 20.0),
        "span_length": (6000.0, 60000.0),
        "num_lanes": (1.0, 8.0),
        "lane_width": (2750.0, 4500.0),
        "sidewalk_width": (0.0, 5000.0),
        "num_piers": (0.0, 19.0),
        "pier_height": (1000.0, 40000.0),
        "pier_width": (500.0, 5000.0),
        "pier_depth": (500.0, 8000.0),
        "abutment_height": (1000.0, 20000.0),
        "abutment_width": (4000.0, 40000.0),
        "abutment_depth": (1000.0, 10000.0),
        "deck_thickness": (150.0, 600.0),
        "girder_height": (400.0, 3500.0),
        "girder_width": (200.0, 1500.0),
        "girder_web_thickness": (100.0, 600.0),
        "girder_flange_thickness": (80.0, 500.0),
        "num_girders": (2.0, 20.0),
        "barrier_height": (800.0, 1500.0),
        "barrier_post_spacing": (1000.0, 5000.0),
        "bearing_length": (200.0, 1000.0),
        "bearing_width": (150.0, 1000.0),
        "bearing_height": (30.0, 300.0),
        "pile_diameter": (300.0, 3000.0),
        "pile_depth": (3000.0, 80000.0),
        "num_piles_per_pier": (1.0, 40.0),
        "pile_cap_thickness": (500.0, 4000.0),
        "clearance_height": (0.0, 20000.0),
    },
}


def validate_spec_bounds(spec: Any) -> None:
    """Validate numeric fields of BuildingSpec or BridgeSpec against SPEC_BOUNDS.

    Raises:
        ValueError: If spec is not a supported dataclass, any numeric field is missing from
                    SPEC_BOUNDS, not a valid number/NaN, out of bounds, or an int field
                    receives a float with fractional part.
    """
    if not is_dataclass(spec):
        raise ValueError("Spec phải là một dataclass instance")

    if isinstance(spec, BridgeSpec):
        structure_type = "bridge"
    elif type(spec).__name__ == "BuildingSpec":
        structure_type = "building"
    else:
        raise ValueError(f"Không hỗ trợ kiểm tra giới hạn cho lớp {type(spec).__name__}")

    bounds_map = SPEC_BOUNDS[structure_type]
    violations = []

    for f in fields(spec):
        # Determine if field is numeric
        is_int_field = f.type in (int, "int")
        is_float_field = f.type in (float, "float")
        if not (is_int_field or is_float_field):
            if isinstance(f.default, bool):
                continue
            if isinstance(f.default, int):
                is_int_field = True
            elif isinstance(f.default, float):
                is_float_field = True
            else:
                continue

        val = getattr(spec, f.name)

        if f.name not in bounds_map:
            violations.append(f"{f.name} chưa có giới hạn")
            continue

        min_val, max_val = bounds_map[f.name]
        min_str = int(min_val) if min_val == int(min_val) else min_val
        max_str = int(max_val) if max_val == int(max_val) else max_val
        bound_str = f"{min_str}–{max_str}"

        # bool is an int subclass in Python -> reject
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            violations.append(f"{f.name}={val} (cho phép {bound_str})")
            continue

        if isinstance(val, float) and math.isnan(val):
            violations.append(f"{f.name}={val} (cho phép {bound_str})")
            continue

        # int field with fractional float
        if is_int_field and isinstance(val, float) and not val.is_integer():
            violations.append(f"{f.name}={val} (cho phép {bound_str})")
            continue

        if val < min_val or val > max_val:
            violations.append(f"{f.name}={val} (cho phép {bound_str})")

    if violations:
        raise ValueError(
            f"Thông số vi phạm giới hạn: {', '.join(violations)}"
        )
