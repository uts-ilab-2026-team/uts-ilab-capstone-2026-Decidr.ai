from datetime import date

import pytest
from pydantic import ValidationError

from decidr.models import AtomicClaim, ClaimEvidenceLink, EvidenceRelationship, Source


def test_source_rejects_reversed_effective_period():
    with pytest.raises(ValidationError):
        Source(
            source_id="POL-01",
            title="Policy",
            original_file_path="policy.md",
            source_type="policy",
            effective_start_date=date(2025, 2, 1),
            effective_end_date=date(2025, 1, 1),
            checksum="a" * 64,
        )


def test_excluded_claim_requires_reason():
    with pytest.raises(ValidationError):
        AtomicClaim(
            claim_id="C1",
            subject="Sales",
            predicate="requires",
            object="approval",
            claim_type="decision_right",
            claim_text="Sales requires approval.",
            inclusion_status="excluded",
        )


def test_not_applicable_link_requires_a_failed_dimension():
    with pytest.raises(ValidationError):
        ClaimEvidenceLink(
            link_id="L1",
            claim_id="C1",
            evidence_id="E1",
            relationship=EvidenceRelationship.NOT_APPLICABLE,
            applicability_reason="No mismatch was recorded.",
            target_match=True,
            scope_match=True,
            condition_match=True,
            temporal_match=True,
            reviewer="reviewer-a",
        )
