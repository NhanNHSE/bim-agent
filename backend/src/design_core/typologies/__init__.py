"""Loader helpers for typology rules and sample programs."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from src.design_core.program import KindRule, Program

_TYPOLOGIES_DIR = Path(__file__).resolve().parent


@lru_cache(maxsize=16)
def load_rules(typology: str) -> dict[str, KindRule]:
    """Read `typologies/<typology>/rules.json` and return a mapping of kind -> KindRule."""
    rules_path = _TYPOLOGIES_DIR / typology / "rules.json"
    raw = json.loads(rules_path.read_text(encoding="utf-8"))
    return {kind: KindRule.model_validate(spec) for kind, spec in raw["kinds"].items()}


@lru_cache(maxsize=16)
def load_samples(typology: str) -> list[Program]:
    """Read `typologies/<typology>/samples.json` and return validated Program objects."""
    samples_path = _TYPOLOGIES_DIR / typology / "samples.json"
    raw = json.loads(samples_path.read_text(encoding="utf-8"))
    return [Program.model_validate(item) for item in raw["samples"]]
