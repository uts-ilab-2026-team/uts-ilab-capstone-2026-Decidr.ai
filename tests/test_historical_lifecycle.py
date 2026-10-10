"""Historical lifecycle scoring without rewriting source provenance."""

from datetime import date
import unittest

from framework import CONFIG_PATH, GraphCredibilityFramework, GraphFactsRegister
from framework.config import GraphCredibilityConfig
from framework.graph import OrganisationalGraph
from framework.models import GraphEdge, GraphNode


def assess(status="superseded", *, when="2024-06-01", count=1, same_origin=False, **overrides):
    nodes = [GraphNode("fact:test", "fact", "Approval is required")]
    edges = []
    for index in range(count):
        attributes = {
            "source_class": "approved_policy",
            "approval_status": "approved",
            "status": status,
            "effective_date": "2021-06-01",
            "effective_end_date": "2025-02-28",
            "duplicate_group": "shared" if same_origin else str(index),
            **overrides,
        }
        nodes.append(GraphNode(f"document:{index}", "document", "Policy", attributes))
        edges.append(
            GraphEdge(
                f"edge:{index}",
                f"document:{index}",
                "fact:test",
                "FORMAL",
                {
                    "attests_value": "Approval is required",
                    "agrees": True,
                    "directness": 1.0,
                    "specificity": 1.0,
                    "completeness": 1.0,
                },
            )
        )
    engine = GraphCredibilityFramework(
        OrganisationalGraph(nodes, edges, version="historical-test"),
        GraphCredibilityConfig.load(CONFIG_PATH),
    )
    return GraphFactsRegister(engine, as_of=date.fromisoformat(when)).get("fact:test")


class HistoricalLifecycleTests(unittest.TestCase):
    def test_historical_score_matches_current_and_preserves_status(self):
        current, historical = assess("current"), assess()
        self.assertEqual(historical.overall_outcome, "Supported")
        self.assertEqual(
            historical.evidence[0].materiality_score, current.evidence[0].materiality_score
        )
        self.assertEqual(historical.evidence[0].lifecycle_status, "superseded")
        self.assertTrue(
            any("Historical lifecycle" in line for line in historical.evidence[0].trace)
        )

    def test_explicit_boundaries_are_inclusive(self):
        for when in ("2021-06-01", "2025-02-28"):
            with self.subTest(when=when):
                self.assertEqual(assess(when=when).overall_outcome, "Supported")

    def test_outside_interval_is_excluded(self):
        for when in ("2021-05-31", "2025-03-01"):
            with self.subTest(when=when):
                evidence = assess(when=when).evidence[0]
                self.assertFalse(evidence.applicable)
                self.assertIsNone(evidence.materiality_score)

    def test_missing_boundary_does_not_restore_lifecycle(self):
        for field in ("effective_date", "effective_end_date"):
            with self.subTest(field=field):
                result = assess(**{field: None})
                self.assertEqual(result.overall_outcome, "Insufficient evidence")
                self.assertFalse(
                    any("Historical lifecycle" in line for line in result.evidence[0].trace)
                )

    def test_independent_historical_sources_corroborate(self):
        historical, current = assess(count=2), assess("current", count=2)
        self.assertEqual(historical.evidence[0].dimensions["corroboration"], 0.75)
        self.assertEqual(
            historical.evidence[0].materiality_score, current.evidence[0].materiality_score
        )

    def test_duplicate_origins_do_not_add_corroboration(self):
        one, repeated = assess(), assess(count=2, same_origin=True)
        self.assertEqual(repeated.evidence[0].dimensions["corroboration"], 0.5)
        self.assertEqual(one.evidence[0].materiality_score, repeated.evidence[0].materiality_score)

    def test_approval_is_not_inferred_from_dates(self):
        result = assess(count=2, approval_status="superseded")
        self.assertEqual(result.evidence[0].dimensions["approval_status"], 0.1)
        self.assertEqual(result.evidence[0].dimensions["corroboration"], 0.5)

    def test_other_lifecycle_states_are_not_promoted(self):
        for status in ("draft", "unknown"):
            with self.subTest(status=status):
                result = assess(status)
                self.assertFalse(
                    any("Historical lifecycle" in line for line in result.evidence[0].trace)
                )
