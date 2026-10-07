"""Configuration record for the graph-governed credibility framework."""

from __future__ import annotations

import json
import math
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
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise GraphValidationError(
                f"Invalid graph credibility configuration JSON: {error}"
            ) from error
        if not isinstance(payload, dict):
            raise GraphValidationError("Graph credibility configuration must be an object")
        try:
            return cls(**payload)
        except TypeError as error:
            raise GraphValidationError(
                f"Invalid graph credibility configuration: {error}"
            ) from error

    def __post_init__(self) -> None:
        if not isinstance(self.config_version, str) or not self.config_version.strip():
            raise GraphValidationError("config_version must be a non-empty string")

        for name in (
            "materiality_threshold", "conflict_ratio", "undated_weight", "stale_weight"
        ):
            self._validate_weight(name, getattr(self, name), bounded=True)

        for name in (
            "dimension_weights", "source_class_weights",
            "approval_weights", "lifecycle_multipliers",
        ):
            weights = getattr(self, name)
            if not isinstance(weights, dict):
                raise GraphValidationError(f"{name} must be an object of numeric weights")
            for key, value in weights.items():
                if not isinstance(key, str) or not key.strip():
                    raise GraphValidationError(f"{name} keys must be non-empty strings")
                self._validate_weight(
                    f"{name}.{key}", value, bounded=name != "dimension_weights"
                )

        if set(self.dimension_weights) != set(CREDIBILITY_DIMENSIONS):
            raise GraphValidationError(
                "Graph credibility weights must cover exactly the same declared dimensions"
            )
        total = sum(self.dimension_weights.values())
        self._validate_weight("dimension_weights total", total, bounded=False)
        if total <= 0:
            raise GraphValidationError("Dimension weights must total above zero")
        if type(self.recency_years) is not int or self.recency_years < 0:
            raise GraphValidationError("recency_years must be a non-negative integer")

    @staticmethod
    def _validate_weight(name: str, value: object, *, bounded: bool) -> None:
        if type(value) not in (int, float):
            raise GraphValidationError(f"{name} must be a number, not a boolean or string")
        try:
            finite = math.isfinite(value)
        except OverflowError:
            finite = False
        if not finite:
            raise GraphValidationError(f"{name} must be finite")
        if value < 0 or (bounded and value > 1):
            permitted = "between 0 and 1" if bounded else "non-negative"
            raise GraphValidationError(f"{name} must be {permitted}")
