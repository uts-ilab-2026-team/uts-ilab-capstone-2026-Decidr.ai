"""Standalone facts register derived from the organisational graph."""

import csv
from dataclasses import asdict, dataclass
from datetime import date
from io import StringIO
import json

from .core import FactAssessment, GraphCredibilityFramework


@dataclass(frozen=True, slots=True)
class GraphFactRecord:
    fact_id: str
    statement: str
    category: str
    status: str
    formal_outcome: str
    observed_outcome: str
    overall_outcome: str
    confidence: str
    formal_values: tuple[str, ...]
    observed_values: tuple[str, ...]
    documents: tuple[str, ...]
    gaps: tuple[str, ...]
    related_qualifiers: tuple[str, ...]
    derivation_summary: str

    def model_dump(self) -> dict[str, object]:
        return asdict(self)


class GraphFactsRegister:
    """Create a graph-native register without touching the relational register."""

    def __init__(self, framework: GraphCredibilityFramework, *, as_of: date) -> None:
        self.framework = framework
        self.as_of = as_of

    def get(self, fact_id: str) -> GraphFactRecord:
        assessment = self.framework.evaluate_fact(fact_id, as_of=self.as_of)
        return self._record(assessment)

    def list_records(self) -> list[GraphFactRecord]:
        return [self.get(fact.node_id) for fact in self.framework.graph.fact_nodes()]

    def _record(self, assessment: FactAssessment) -> GraphFactRecord:
        if not assessment.evidence:
            status = "Candidate - no evidence"
        elif assessment.overall_outcome == "Insufficient evidence":
            status = "Graph reviewed - unresolved evidence gap"
        else:
            status = "Graph-assessed finding"
        return GraphFactRecord(
            fact_id=assessment.fact_id,
            statement=assessment.statement,
            category=assessment.category,
            status=status,
            formal_outcome=assessment.formal_outcome,
            observed_outcome=assessment.observed_outcome,
            overall_outcome=assessment.overall_outcome,
            confidence=assessment.confidence,
            formal_values=tuple(
                item.attests_value for item in assessment.evidence if item.mode == "formal"
            ),
            observed_values=tuple(
                item.attests_value for item in assessment.evidence if item.mode == "observed"
            ),
            documents=tuple(dict.fromkeys(item.document_id for item in assessment.evidence)),
            gaps=assessment.gaps,
            related_qualifiers=assessment.related_qualifiers,
            derivation_summary=assessment.summary,
        )

    def to_json(self) -> str:
        return json.dumps([item.model_dump() for item in self.list_records()], indent=2)

    def to_csv(self) -> str:
        columns = (
            "fact_id",
            "statement",
            "category",
            "status",
            "formal_outcome",
            "observed_outcome",
            "overall_outcome",
            "confidence",
            "formal_values",
            "observed_values",
            "documents",
            "gaps",
            "related_qualifiers",
            "derivation_summary",
        )
        handle = StringIO(newline="")
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for record in self.list_records():
            row = record.model_dump()
            for field_name in (
                "formal_values",
                "observed_values",
                "documents",
                "gaps",
                "related_qualifiers",
            ):
                row[field_name] = json.dumps(row[field_name])
            writer.writerow(row)
        return handle.getvalue()
