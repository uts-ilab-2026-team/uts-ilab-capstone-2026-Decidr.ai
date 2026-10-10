"""JSON-safe response for isolated facet assessments."""

import json

from decidr.assessment_adapter import FacetAssessmentResult


def serialize_facet_assessment(result: FacetAssessmentResult) -> dict:
    """Preserve every input and disposition without silently rescoring it."""
    payload = {
        "schema_version": "facet-assessment-response-v1",
        "assessment_scope": "facet",
        "interpretation_basis": "supplied_judgements",
        "claim_text": result.claim_text,
        "facet": result.facet,
        "as_of": result.as_of.isoformat(),
        "assessment": result.assessment.model_dump(),
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
    return json.loads(json.dumps(payload, ensure_ascii=False, allow_nan=False))
