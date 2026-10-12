"""Directional containment preserves scope and never infers permission from silence."""

from datetime import date

import pytest

from decidr.approval_propositions import compare_approval_rules
from decidr.interpretation_engine import propose_interpretation
from decidr.retrieval_models import Evidence, Source


def rule(boundary):
    return (f"Any discount of {boundary} off list price on a wholesale deal requires "
            "written approval from the Operations Director before the deal is marked Signed.")


@pytest.mark.parametrize("claim,evidence,expected", [
    ("exactly 15%", "15% or greater", True),
    ("15%", "above 15%", False),
    ("above 15%", "15% or greater", True),
    ("15% or greater", "above 15%", False),
    ("at least 20%", "at least 15%", True),
    ("at least 15%", "at least 20%", False),
    ("12.501%", "above 12.5%", True),
    ("12.50%", "above 12.5%", False),
    ("at most 12%", "at most 15%", True),
    ("at most 15%", "at most 12%", False),
    ("below 15%", "at most 15%", True),
    ("at most 15%", "below 15%", False),
    ("15%", "at most 15%", True),
    ("15%", "below 15%", False),
    ("0%", "at least 0%", True),
    ("100%", "at most 100%", True),
    ("above 100%", "at least 0%", False),
    ("below 0%", "at most 100%", False),
    ("100%", "above 100%", False),
    ("0%", "below 0%", False),
    ("at least 15%", "at most 20%", False),
    ("at most 20%", "at least 15%", False),
    ("16%", "15%", False),
])
def test_ranges(claim, evidence, expected):
    result = compare_approval_rules(rule(claim), rule(evidence))
    assert result["claim_range_covered"] is expected
    assert result["evidence_entails_claim"] is expected


@pytest.mark.parametrize("old,new", [
    ("Operations Director", "Sales Director"), ("wholesale", "renewal"),
    ("before", "after"), ("written approval", "approval"), ("Signed", "Closed"),
])
def test_boundary_match_cannot_override_other_fields(old, new):
    result = compare_approval_rules(rule("15%").replace(old, new), rule("at least 15%"))
    assert result["claim_range_covered"] is True
    assert result["evidence_entails_claim"] is False


def proposal(claim_boundary, evidence_boundary):
    text = rule(evidence_boundary)
    source = Source(source_id="s", title="Policy", original_file_path="test.md",
                    source_type="policy", checksum="a" * 64, approval_status="Approved",
                    lifecycle_status="current", effective_start_date=date(2025, 1, 1))
    evidence = Evidence(evidence_id="e", source_id="s", locator="p:1", text=text,
                        source_type="policy", extraction_method="test")
    claim = rule(claim_boundary)
    return propose_interpretation(claim_text=claim, facet=claim, assessment_target="formal_rule",
                                   as_of=date(2026, 6, 17), evidence=evidence, source=source)


def test_engine_proposes_support_with_original_quote_and_unverified_authority():
    result = proposal("exactly 15%", "15% or greater")
    assert result.stance == "support"
    assert result.comparison_method == "approval_fields_v2"
    assert "covers" in result.rationale
    assert result.citation.quotation == rule("15% or greater")
    assert result.authority_verified is None
    assert (result.directness, result.specificity, result.completeness) == (0, 0, 0)


def test_engine_does_not_treat_missing_coverage_as_contradiction():
    result = proposal("15%", "above 15%")
    assert result.stance == "unresolved"


def test_empty_range_abstains_even_for_identical_text():
    assert proposal("above 100%", "above 100%").stance == "unresolved"
