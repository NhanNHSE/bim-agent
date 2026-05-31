"""Base specification classes for all structure types.

Provides BaseSpec (shared fields) and BridgeSpec for bridge generation.
BuildingSpec remains in ifc_generator_v2.py for backward compatibility.
"""

from dataclasses import dataclass, field
from typing import Optional


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
