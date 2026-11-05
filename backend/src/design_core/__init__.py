"""Design core package: architectural program schemas, CP-SAT layout solver, and 2D plan drawing."""

from src.design_core.draw import draw_layout, load_font
from src.design_core.layout import (
    Connection,
    FloorLayout,
    Layout,
    LayoutInfeasible,
    PlacedRoom,
    SolveStats,
    solve_layout,
)
from src.design_core.program import FloorReq, KindRule, Lot, Program, RoomReq, StairSpec
from src.design_core.typologies import load_rules, load_samples

__all__ = [
    "Connection",
    "FloorLayout",
    "FloorReq",
    "KindRule",
    "Layout",
    "LayoutInfeasible",
    "Lot",
    "PlacedRoom",
    "Program",
    "RoomReq",
    "SolveStats",
    "StairSpec",
    "draw_layout",
    "load_font",
    "load_rules",
    "load_samples",
    "solve_layout",
]
