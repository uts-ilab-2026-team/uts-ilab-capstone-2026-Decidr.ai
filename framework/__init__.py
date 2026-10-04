"""Graph-governed credibility framework and facts-register logic.

A standalone, deterministic method for assessing organisational claims against a
knowledge graph.  This package intentionally does not import or write to the
existing relational credibility framework.
"""

from pathlib import Path

from framework.constants import CREDIBILITY_DIMENSIONS, CREDIBILITY_QUESTIONS
from framework.credibility import GraphCredibilityFramework
from framework.graph import OrganisationalGraph
from framework.models import FactAssessment
from framework.register import GraphFactsRegister

PACKAGE_ROOT = Path(__file__).resolve().parent
GRAPH_PATH = PACKAGE_ROOT / "data" / "prototype_graph.json"
CONFIG_PATH = PACKAGE_ROOT / "data" / "credibility.json"

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
