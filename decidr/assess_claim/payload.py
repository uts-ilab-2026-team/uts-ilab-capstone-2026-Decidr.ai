"""Frontend payload — serialise a ClaimAssessment into a plain JSON-safe dict."""

from __future__ import annotations

from typing import TYPE_CHECKING

from decidr.assess_claim.confidence import _reconcile_confidence
from decidr.finding_shim import _strip_release
from decidr.graph.models import FactAssessment

if TYPE_CHECKING:
    from decidr.assess_claim.types import ClaimAssessment


def _score(value: float | None) -> float | None:
    return None if value is None else round(value, 3)


def _group_evidence(
    assessment: FactAssessment | None, via_by_code: dict[str, set[str]]
) -> list[dict]:
    """Group edges by (source, mode) into one entry per document, each listing its passages.

    Edges from the SAME document are different *passages* of that document — distinct evidence,
    but one source. We collapse them to a single source entry (so the UI shows one row per
    document) and append every passage underneath, keeping each quote, stance and score.
    ``retrieved_via`` records how this source reached the reader (graph_governed / keyword / both).
    """
    if assessment is None:
        return []
    grouped: dict[tuple[str, str], dict] = {}
    for edge in assessment.evidence:
        source = edge.document_id.replace("document:", "")
        key = (source, edge.mode)
        entry = grouped.setdefault(
            key,
            {
                "source": source,
                "title": edge.document_title,
                "mode": edge.mode,
                "source_class": edge.source_class,
                "lifecycle_status": edge.lifecycle_status,
                "retrieved_via": sorted(via_by_code.get(source, set())),
                "material": False,
                "best_score": None,
                "passages": [],
            },
        )
        entry["passages"].append(
            {
                "quote": edge.attests_value,
                "stance": edge.stance,
                "applicable": edge.applicable,
                "material": edge.material,
                "score": _score(edge.materiality_score),
                "limitations": list(edge.limitations),
                "trace": list(edge.trace),
            }
        )
        entry["material"] = entry["material"] or edge.material
        if edge.materiality_score is not None:
            best = entry["best_score"]
            entry["best_score"] = (
                edge.materiality_score if best is None else max(best, edge.materiality_score)
            )
    for entry in grouped.values():
        entry["best_score"] = _score(entry["best_score"])
    return list(grouped.values())


def to_payload(result: ClaimAssessment) -> dict:
    """Serialise a ClaimAssessment into the shape a UI consumes (JSON-safe)."""
    predicate_by_id = {c["id"]: c.get("predicate", "") for c in result.split["components"]}
    text_by_id = {c["id"]: c.get("text", "") for c in result.split["components"]}
    decisive_facets = {f.facet: f.decisive for f in result.verdict.facets}

    # Map each source code -> how its passages were retrieved, from the tagged passage list.
    via_by_code: dict[str, set[str]] = {}
    for passage in result.passages:
        code = _strip_release(passage["source_id"])
        via_by_code.setdefault(code, set()).add(passage["retrieved_via"])

    # One reconciled confidence per level: facet (score, tier) pairs plus the weakest-link claim
    # score and tier, all from the same calculation so number and label never disagree.
    facet_conf, claim_confidence_score, claim_confidence = _reconcile_confidence(result)
    facets = []
    for facet in result.verdict.facets:
        assessment = result.facet_assessments.get(facet.facet)
        score, tier = facet_conf[facet.facet]
        facets.append(
            {
                "facet": facet.facet,
                "predicate": predicate_by_id.get(facet.facet, ""),
                "summary": text_by_id.get(facet.facet, ""),
                "outcome": facet.outcome,
                "confidence": tier,
                "confidence_score": score,
                "decisive": decisive_facets.get(facet.facet, True),
                "evidence": _group_evidence(assessment, via_by_code),
            }
        )

    return {
        "claim": result.claim_text,
        "as_of": str(result.as_of),
        "overall_outcome": result.verdict.overall_outcome,
        "confidence": claim_confidence,
        "confidence_score": claim_confidence_score,
        "target": result.split.get("target"),
        "split_status": result.split["semantic_validation"]["status"],
        "facets": facets,
        "rules_applied": list(result.verdict.rules_applied),
        "retrieval": result.retrieval,
        "passages_considered": len(result.passages),
        "findings_count": len(result.reading.get("findings", [])),
        "notes": result.notes,
    }
