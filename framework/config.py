"""Configuration record for the graph-governed credibility framework."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from framework.constants import CREDIBILITY_DIMENSIONS
from framework.errors import GraphValidationError


@dataclass(frozen=True, slots=True)
class GraphCredibilityConfig:
    config_version: str
    materiality_threshold: float
    conflict_ratio: float
    dimension_weights: dict[str, float]
    source_class_weights: dict[str, float]
    approval_weights: dict[str, float]
    lifecycle_multipliers: dict[str, float]
    undated_weight: float
    stale_weight: float
    recency_years: int

    @classmethod
    def load(cls, path: Path) -> GraphCredibilityConfig:
        payload = json.loads(path.read_text(encoding="utf-8"))
        config = cls(**payload)
        if set(config.dimension_weights) != set(CREDIBILITY_DIMENSIONS):
            raise GraphValidationError(
                "Graph credibility weights must cover exactly the same declared dimensions"
            )
        if not 0 <= config.materiality_threshold <= 1:
            raise GraphValidationError("Materiality_threshold must be between 0 and 1")
        if sum(config.dimension_weights.values()) <= 0:
            raise GraphValidationError("Dimension weights must total above zero")
        return config
