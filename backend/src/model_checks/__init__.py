"""Public interface for automatic IFC4 model checks."""

from src.model_checks.checks import (
    CHECKS,
    LOD200_REQUIRED,
    Issue,
    check_clashes,
    check_columns_on_grid,
    check_extent,
    check_openings,
    check_required_classes,
    check_schema,
    check_spaces,
    check_wall_connections,
    run_all,
)

__all__ = [
    "Issue",
    "LOD200_REQUIRED",
    "CHECKS",
    "run_all",
    "check_schema",
    "check_required_classes",
    "check_openings",
    "check_wall_connections",
    "check_columns_on_grid",
    "check_spaces",
    "check_extent",
    "check_clashes",
]
