"""Graph-governed credibility framework and facts-register logic.

A standalone, deterministic method for assessing organisational claims against a
knowledge graph.  This package intentionally does not import or write to the
existing relational credibility framework.
"""

from pathlib import Path

from decidr.graph.constants import CREDIBILITY_DIMENSIONS, CREDIBILITY_QUESTIONS
from decidr.graph.credibility import GraphCredibilityFramework
from decidr.graph.graph import OrganisationalGraph
from decidr.graph.models import FactAssessment
from decidr.graph.register import GraphFactsRegister

PACKAGE_ROOT = Path(__file__).resolve().parent
GRAPH_PATH = PACKAGE_ROOT / "data" / "prototype_graph.json"
CONFIG_PATH = PACKAGE_ROOT / "data" / "credibility.json"

__all__ = [
    "CONFIG_PATH",
    "CREDIBILITY_DIMENSIONS",
    "CREDIBILITY_QUESTIONS",
    "GRAPH_PATH",
    "FactAssessment",
    "GraphCredibilityFramework",
    "GraphFactsRegister",
    "OrganisationalGraph",
]
