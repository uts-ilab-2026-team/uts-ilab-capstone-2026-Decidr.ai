"""Deterministic credibility reasoning over the organisational graph.

Evaluates a Fact's FORMAL and OBSERVED attestations with a
source -> status -> date discipline, keeping formal and observed evidence in
separate lanes and recording missing evidence as a gap rather than a
contradiction.  The graph structure itself lives in ``framework.graph``.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from framework.config import GraphCredibilityConfig
from framework.constants import CREDIBILITY_DIMENSIONS
from framework.graph import OrganisationalGraph
from framework.models import (
    EdgeAssessment,
    FactAssessment,
    GraphEdge,
    GraphNode,
)


class GraphCredibilityFramework:
    """Evaluate Fact attestations with source -> status -> date discipline."""

    def __init__(self, graph: OrganisationalGraph, config: GraphCredibilityConfig) -> None:
        self.graph = graph
        self.config = config

    @classmethod
    def load(cls, graph_path: Path, config_path: Path) -> GraphCredibilityFramework:
        return cls(
            OrganisationalGraph.load(graph_path),
            GraphCredibilityConfig.load(config_path),
        )

    def evaluate_fact(self, fact_id: str, *, as_of: date) -> FactAssessment:
        fact = self.graph.nodes.get(fact_id)
        if fact is None or fact.kind != "fact":
            raise KeyError(f"Unknown Fact: {fact_id}")
        attestations = self.graph.attestations(fact_id)
        duplicate_counts: dict[str, int] = {}
        corroboration_counts: dict[tuple[str, str], set[str]] = {}
        for edge in attestations:
            if not self._applicable(edge, as_of=as_of):
                continue
            document = self.graph.document(edge.source)
            group = str(document.attributes.get("duplicate_group") or document.node_id)
            duplicate_counts[group] = duplicate_counts.get(group, 0) + 1
            key = (edge.relationship.lower(), self._stance(edge))
            corroboration_counts.setdefault(key, set()).add(group)

        reviewed = tuple(
            self._evaluate_edge(
                edge,
                as_of=as_of,
                duplicate_counts=duplicate_counts,
                corroboration_counts=corroboration_counts,
            )
            for edge in attestations
        )
        formal = self._lane_outcome(reviewed, "formal")
        observed = self._lane_outcome(reviewed, "observed")
        overall = self._overall_outcome(formal, observed)
        gaps = self._gaps(reviewed)
        related = tuple(self.graph.related_qualifiers(fact_id))
        confidence = self._confidence(reviewed, overall, gaps)
        summary = self._summary(formal, observed, overall, confidence, reviewed, related)
        return FactAssessment(
            fact_id=fact_id,
            statement=str(fact.attributes.get("statement", fact.label)),
            category=str(fact.attributes.get("category", "uncategorised")),
            formal_outcome=formal,
            observed_outcome=observed,
            overall_outcome=overall,
            confidence=confidence,
            summary=summary,
            evidence=reviewed,
            gaps=tuple(gaps),
            related_qualifiers=related,
            rules_applied=(
                "GCF1_APPLICABILITY_GATE",
                "GCF2_SOURCE_AUTHORITY_BACKBONE_CHECK",
                "GCF3_LIFECYCLE_STATUS",
                "GCF4_EFFECTIVE_DATE",
                "GCF5_INDEPENDENCE_AND_CORROBORATION",
                "GCF6_FORMAL_OBSERVED_SEPARATION",
                "GCF7_MISSINGNESS_IS_NOT_CONTRADICTION",
            ),
        )

    def _evaluate_edge(
        self,
        edge: GraphEdge,
        *,
        as_of: date,
        duplicate_counts: dict[str, int],
        corroboration_counts: dict[tuple[str, str], set[str]],
    ) -> EdgeAssessment:
        document = self.graph.document(edge.source)
        attributes = document.attributes
        edge_attributes = edge.attributes
        status = str(attributes.get("status", "unknown"))
        source_class = str(attributes.get("source_class", "unknown"))
        applicable = self._applicable(edge, as_of=as_of)
        limitations: list[str] = []
        trace: list[str] = []
        if not applicable:
            temporal_reason = self._temporal_exclusion(document, as_of)
            limitations.append(
                temporal_reason
                or "The attestation does not match the Fact's scope or conditions."
            )
            return EdgeAssessment(
                edge_id=edge.edge_id,
                document_id=document.node_id,
                document_title=document.label,
                mode=edge.relationship.lower(),
                attests_value=str(edge_attributes["attests_value"]),
                stance=self._stance(edge),
                source_class=source_class,
                lifecycle_status=status,
                applicable=False,
                materiality_score=None,
                material=False,
                dimensions={},
                limitations=tuple(limitations),
                trace=(
                    f"Applicability gate failed: {limitations[0]} "
                    "Evidence retained but not scored.",
                ),
            )

        backbone_factor, backbone_trace = self.graph.backbone_resolution(edge)
        authority_base = self.config.source_class_weights.get(source_class, 0.4)
        authority = authority_base * backbone_factor
        trace.append(f"Source: {source_class} authority={authority_base:.2f}. {backbone_trace}")

        approval = self.config.approval_weights.get(
            str(attributes.get("approval_status", "unknown")), 0.5
        )
        lifecycle = self.config.lifecycle_multipliers.get(status, 0.5)
        trace.append(
            f"Status: {status} lifecycle multiplier={lifecycle:.2f}; approval={approval:.2f}."
        )

        recency, recency_note = self._recency(document, as_of)
        trace.append(f"Date: {recency_note} value={recency:.2f}.")

        group = str(attributes.get("duplicate_group") or document.node_id)
        # Score source quality once per origin; repetition must not change it.
        # _lane_outcome applies the origin cap when combining evidence.
        independence = 1.0
        trace.append(
            f"Independence: origin {group!r} contributes at most once per stance "
            "in this lane, using its strongest material assessment."
        )
        stance = self._stance(edge)
        corroborating_origins = len(
            corroboration_counts.get((edge.relationship.lower(), stance), set())
        )
        corroboration = (
            0.5
            if corroborating_origins <= 1
            else min(1.0, 0.5 + 0.25 * (corroborating_origins - 1))
        )
        if duplicate_counts[group] > 1:
            limitations.append("A duplicate source exists and is not counted as independent.")
        if corroborating_origins <= 1:
            limitations.append("No independent source corroborates this stance in the same lane.")

        dimensions = {
            "source_authority": authority,
            "approval_status": approval,
            "version_recency": recency,
            "directness": float(edge_attributes.get("directness", 0.5)),
            "specificity": float(edge_attributes.get("specificity", 0.5)),
            "corroboration": corroboration,
            "source_independence": independence,
            "evidence_completeness": float(edge_attributes.get("completeness", 0.5)),
        }
        total_weight = sum(self.config.dimension_weights.values())
        weighted_average = (
            sum(
                dimensions[name] * self.config.dimension_weights[name]
                for name in CREDIBILITY_DIMENSIONS
            )
            / total_weight
        )
        score = weighted_average * lifecycle * max(authority, 0.1)
        material = score >= self.config.materiality_threshold
        if edge_attributes.get("gap"):
            limitations.append(str(edge_attributes["gap"]))
        trace.append(
            "Materiality: weighted dimensions "
            f"{weighted_average:.3f} × lifecycle {lifecycle:.2f} × authority "
            f"{max(authority, 0.1):.2f} = {score:.3f}."
        )
        return EdgeAssessment(
            edge_id=edge.edge_id,
            document_id=document.node_id,
            document_title=document.label,
            mode=edge.relationship.lower(),
            attests_value=str(edge_attributes["attests_value"]),
            stance=stance,
            source_class=source_class,
            lifecycle_status=status,
            applicable=True,
            materiality_score=score,
            material=material,
            dimensions=dimensions,
            limitations=tuple(limitations),
            trace=tuple(trace),
        )

    def _applicable(self, edge: GraphEdge, *, as_of: date) -> bool:
        """Return True if the attestation matches scope and its effective period.

        Single source of truth for applicability: used both to skip non-applicable
        edges in the pre-pass tally and to gate scoring in ``_evaluate_edge``.
        """
        attributes = edge.attributes
        scope_matches = bool(attributes.get("applicable", True)) and bool(
            attributes.get("scope_match", True)
        )
        document = self.graph.document(edge.source)
        return scope_matches and self._temporal_exclusion(document, as_of) is None

    @staticmethod
    def _temporal_exclusion(document: GraphNode, as_of: date) -> str | None:
        start = document.attributes.get("effective_date")
        end = document.attributes.get("effective_end_date")
        if start and date.fromisoformat(str(start)) > as_of:
            return "The document is not yet effective at the assessment date."
        if end and date.fromisoformat(str(end)) < as_of:
            return "The document is no longer effective at the assessment date."
        return None

    def _recency(self, document: GraphNode, as_of: date) -> tuple[float, str]:
        start_text = document.attributes.get("effective_date")
        end_text = document.attributes.get("effective_end_date")
        updated_text = document.attributes.get("last_updated")
        if start_text and date.fromisoformat(str(start_text)) > as_of:
            return 0.0, "document was not yet effective"
        if end_text and date.fromisoformat(str(end_text)) < as_of:
            return self.config.stale_weight, "document was no longer effective"
        if not start_text and not updated_text:
            return (
                self.config.undated_weight,
                "no effective or updated date was available",
            )
        anchor = date.fromisoformat(str(updated_text or start_text))
        age_years = max(0.0, (as_of - anchor).days / 365.25)
        if age_years > self.config.recency_years:
            return self.config.stale_weight, f"source was {age_years:.1f} years old"
        return 1.0, "source aligned with the assessment date"

    @staticmethod
    def _stance(edge: GraphEdge) -> str:
        agrees = edge.attributes.get("agrees")
        if agrees is True:
            return "support"
        if agrees is False:
            return "contradict"
        return "qualify"

    def _origin_id(self, document_id: str) -> str:
        document = self.graph.document(document_id)
        return str(document.attributes.get("duplicate_group") or document.node_id)

    def _lane_outcome(self, reviewed: tuple[EdgeAssessment, ...], mode: str) -> str:
        # Retain every edge, but count only the strongest material assessment
        # from each origin for each stance within this lane.
        contributions: dict[tuple[str, str], float] = {}
        for item in reviewed:
            if item.mode != mode or not item.material:
                continue
            if item.stance not in {"support", "contradict"}:
                continue
            key = (self._origin_id(item.document_id), item.stance)
            contributions[key] = max(
                contributions.get(key, 0.0), item.materiality_score or 0.0
            )
        support = sum(
            score for (_, stance), score in contributions.items() if stance == "support"
        )
        contradict = sum(
            score for (_, stance), score in contributions.items() if stance == "contradict"
        )
        if not support and not contradict:
            return "Insufficient evidence"
        if support and contradict:
            ratio = min(support, contradict) / max(support, contradict)
            if ratio >= self.config.conflict_ratio:
                return "Contested"
        return "Supported" if support > contradict else "Contradicted"

    @staticmethod
    def _overall_outcome(formal: str, observed: str) -> str:
        decisive = [item for item in (formal, observed) if item != "Insufficient evidence"]
        if not decisive:
            return "Insufficient evidence"
        if "Contested" in decisive or len(set(decisive)) > 1:
            return "Contested"
        return decisive[0]

    def _gaps(self, reviewed: tuple[EdgeAssessment, ...]) -> list[str]:
        gaps = []
        if not reviewed:
            gaps.append("No Document or structured row attests to this Fact.")
        for mode in ("formal", "observed"):
            decisive = [
                item
                for item in reviewed
                if item.mode == mode and item.material and item.stance in {"support", "contradict"}
            ]
            if not decisive:
                gaps.append(f"No material {mode} attestation resolves the asserted value.")
        for item in reviewed:
            for limitation in item.limitations:
                if "missing" in limitation.casefold() or "no linked" in limitation.casefold():
                    gaps.append(limitation)
        return list(dict.fromkeys(gaps))

    def _confidence(
        self, reviewed: tuple[EdgeAssessment, ...], overall: str, gaps: list[str]
    ) -> str:
        decisive = [
            item for item in reviewed if item.material and item.stance in {"support", "contradict"}
        ]
        non_material_divergence = any(
            item.applicable and not item.material and item.stance == "contradict"
            for item in reviewed
        )
        if overall == "Insufficient evidence":
            return "Lower confidence"
        if overall == "Contested" or non_material_divergence or gaps:
            return "Moderate confidence"
        independent_origins = {self._origin_id(item.document_id) for item in decisive}
        return "Higher confidence" if len(independent_origins) >= 2 else "Moderate confidence"

    @staticmethod
    def _summary(
        formal: str,
        observed: str,
        overall: str,
        confidence: str,
        reviewed: tuple[EdgeAssessment, ...],
        related: tuple[str, ...],
    ) -> str:
        divergence = [item for item in reviewed if item.stance == "contradict" and item.applicable]
        parts = [
            f"Formal evidence: {formal}.",
            f"Observed evidence: {observed}.",
            f"Combined outcome: {overall}; {confidence.lower()}.",
        ]
        if divergence:
            parts.append(
                "Practice divergence is retained in the trace even where its source weight is "
                "not decisive."
            )
        if related:
            parts.append("Related Facts narrow the scope and are reported as qualifications.")
        return " ".join(parts)
