"""JSON-ready facet assessments with all supplied interpretations preserved."""

from dataclasses import asdict
import json

from decidr.assessment_adapter import FacetAssessmentResult


def serialize_facet_assessment(result: FacetAssessmentResult) -> dict:
    """Preserve adapter results without reclassifying or rescoring evidence.

    Admission means an edge entered the framework, not that it independently
    decided the verdict. Materiality and dependence remain in the core trace.
    Supplied interpretations are not automatically human-reviewed judgements.
    """
    payload = {
        "schema_version": "facet-assessment-response-v1",
        "assessment_scope": "facet",
        "assessment_target": result.assessment_target,
        "target_validation": (
            "not_performed_legacy"
            if result.assessment_target == "unspecified"
            else "supplied_declarations_checked"
        ),
        "interpretation_basis": "supplied_judgements",
        "assurance": {
            "version": "supplied-assessment-assurance-v1",
            "outcome_basis": "conditional_on_supplied_judgements",
            "citation_validation": "exact_spans_and_identities_checked",
            "semantic_verification": "not_performed",
            "authority_verification": "caller_declared_not_independently_verified",
            "independence_verification": "caller_declared_with_consistency_checks",
            "quality_scores": "caller_supplied_not_calibrated_by_this_endpoint",
            "source_class_and_approval_key": "caller_supplied_configured_keys",
            "human_review": "not_established_by_this_request",
            "notice": (
                "Verdict and confidence are conditional on supplied interpretations and "
                "credibility judgements. Exact citation checks do not verify those judgements."
            ),
        },
        "claim_text": result.claim_text,
        "facet": result.facet,
        "as_of": result.as_of.isoformat(),
        "assessment": asdict(result.assessment),
        "inputs": [
            {
                "input_id": item.input_id,
                "interpretation": item.interpretation.model_dump(mode="json"),
                "source": item.source.model_dump(mode="json"),
                "supplied_judgements": item.supplied_judgements,
                "edge_id": item.edge_id,
                "admitted_to_framework": item.edge_id is not None,
                "reasons": list(item.reasons),
            }
            for item in result.inputs
        ],
        "limitations": list(result.limitations),
    }
    # Produce detached JSON primitives and reject non-finite numeric values.
    # Do not stringify unsupported values: serialization errors must be visible.
    return json.loads(json.dumps(payload, ensure_ascii=False, allow_nan=False))
