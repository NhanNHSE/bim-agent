"""Loader helpers for typology rules and sample programs."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from src.design_core.program import KindRule, Program, TypologyRules

_TYPOLOGIES_DIR = Path(__file__).resolve().parent


@lru_cache(maxsize=16)
def load_typology(typology: str) -> TypologyRules:
    """Read `typologies/<typology>/rules.json` and return a validated TypologyRules."""
    rules_path = _TYPOLOGIES_DIR / typology / "rules.json"
    raw = json.loads(rules_path.read_text(encoding="utf-8"))
    kinds = {kind: KindRule.model_validate(spec) for kind, spec in raw["kinds"].items()}
    sh_raw = raw["storey_heights_m"]
    msh_raw = raw["min_storey_height_m"]
    bp_raw = raw["balcony_projection"]
    return TypologyRules(
        kinds=kinds,
        storey_heights_m=[float(v) for v in sh_raw["values"]],
        min_storey_height_m=float(msh_raw["value"]),
        balcony_projection=list(bp_raw["table"]),
        sources={
            "storey_heights_m": sh_raw,
            "min_storey_height_m": msh_raw,
            "balcony_projection": bp_raw,
        },
    )


@lru_cache(maxsize=16)
def load_rules(typology: str) -> dict[str, KindRule]:
    """Read `typologies/<typology>/rules.json` and return a mapping of kind -> KindRule."""
    return load_typology(typology).kinds


def balcony_projection_m(typology: str, street_width_m: float | None) -> float:
    """Return max allowed balcony projection (m) for `street_width_m` under `typology`."""
    if street_width_m is None:
        return 0.0
    table = load_typology(typology).balcony_projection
    eligible = [row for row in table if float(row["min_street_m"]) <= street_width_m]
    if not eligible:
        return 0.0
    best = max(eligible, key=lambda row: float(row["min_street_m"]))
    return float(best["max_m"])


@lru_cache(maxsize=16)
def load_samples(typology: str) -> list[Program]:
    """Read `typologies/<typology>/samples.json` and return validated Program objects."""
    samples_path = _TYPOLOGIES_DIR / typology / "samples.json"
    raw = json.loads(samples_path.read_text(encoding="utf-8"))
    return [Program.model_validate(item) for item in raw["samples"]]
