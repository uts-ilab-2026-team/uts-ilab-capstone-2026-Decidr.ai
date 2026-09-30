"""Graph-governed credibility framework and facts-register logic."""

from pathlib import Path

from .core import (
    CREDIBILITY_DIMENSIONS,
    CREDIBILITY_QUESTIONS,
    FactAssessment,
    GraphCredibilityFramework,
    OrganisationalGraph,
)
from .register import GraphFactsRegister

PACKAGE_ROOT = Path(__file__).resolve().parent
GRAPH_PATH = PACKAGE_ROOT / "data" / "prototype_graph.json"
CONFIG_PATH = PACKAGE_ROOT / "config" / "credibility.json"

__all__ = [
    "CREDIBILITY_DIMENSIONS",
    "CREDIBILITY_QUESTIONS",
    "FactAssessment",
    "CONFIG_PATH",
    "GRAPH_PATH",
    "GraphCredibilityFramework",
    "GraphFactsRegister",
    "OrganisationalGraph",
]
