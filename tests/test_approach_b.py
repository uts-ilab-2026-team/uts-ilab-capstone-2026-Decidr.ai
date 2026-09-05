import json

from decidr.approach_b import (
    BoundedGraphExpander,
    ConstrainedClaimParser,
    StrictCitationValidator,
    load_profile,
)
from decidr.comparison import comparison_readiness
from decidr.config import PROJ_ROOT
from decidr.database import connect, reset_test_records, save_claim_assessment
from decidr.models import AtomicClaim, ClaimAssessment, ClaimOutcome, ConfidenceLevel


def test_parser_splits_rule_and_practice_without_inventing_period():
    proposal = ConstrainedClaimParser().parse_proposal(
        "What is the new-business 15% discount rule, and do employees follow it?"
    )

    assert len(proposal.claims) == 2
    assert {claim.evidence_target.value for claim in proposal.claims} == {
        "prescribed_rule", "routine_practice"
    }
    assert all(claim.applicable_start_date is None for claim in proposal.claims)
    assert proposal.clarification is not None


def test_parser_flags_missing_discount_scope_and_threshold():
    proposal = ConstrainedClaimParser().parse_proposal("Does a discount require approval?")

    assert "discount threshold" in proposal.ambiguities
    assert "deal scope" in proposal.ambiguities


def test_citation_validator_rejects_out_of_package_ids():
    package = [{"evidence_id": "E1", "locator": "section:x", "text": "Rule."}]
    result = StrictCitationValidator().validate(
        "The deterministic outcome is Supported [E2].", package, ClaimOutcome.SUPPORTED
    )

    assert result.valid is False
    assert "E2" in result.errors[0]


def test_graph_expansion_rejects_unbounded_depth(tmp_path):
    database = tmp_path / "ledger.sqlite3"
    from decidr.database import initialise_database
    initialise_database(database)
    claim = AtomicClaim(
        claim_id="C", subject="s", predicate="p", object="o",
        claim_type="test", claim_text="test",
    )
    with connect(database) as connection:
        try:
            BoundedGraphExpander(connection).expand(claim, [], depth=2)
        except ValueError as error:
            assert "bounded" in str(error)
        else:
            raise AssertionError("unbounded graph expansion was accepted")


def test_profiles_share_required_reproducibility_metadata():
    profiles = [
        load_profile(PROJ_ROOT / "configs" / "approach_a_baseline.yaml"),
        load_profile(PROJ_ROOT / "configs" / "approach_b_graph_llm.yaml"),
    ]
    assert all(profile["approach_id"] and profile["configuration_version"] for profile in profiles)
    assert profiles[1]["random_seed"] == 2026
    assert profiles[1]["prompt_template_version"]


def test_comparison_keeps_held_out_sealed_until_all_gates_open():
    config = {
        "reasoning_ruleset_status": "development_unfrozen",
        "held_out_access_status": "sealed",
        "final_evaluation_authorised": False,
    }
    readiness = comparison_readiness(config, completed_reviewers=2, development_references=6)
    assert readiness.development_ready is True
    assert readiness.held_out_ready is False


def test_safe_reset_removes_only_test_namespace(tmp_path):
    from decidr.database import initialise_database, save_claim
    database = tmp_path / "ledger.sqlite3"
    initialise_database(database)
    claim = AtomicClaim(
        claim_id="C", subject="s", predicate="p", object="o",
        claim_type="test", claim_text="test",
    )
    with connect(database) as connection:
        save_claim(connection, claim)
        for reviewer in ("test:fixture", "Royston"):
            save_claim_assessment(
                connection,
                ClaimAssessment(
                    assessment_id=f"A-{reviewer}", claim_id="C", reviewer=reviewer,
                    outcome=ClaimOutcome.INSUFFICIENT, confidence=ConfidenceLevel.LOWER,
                    uncertainty_explanation="gap", explanation="test", review_status="complete",
                ), [],
            )
        reset_test_records(connection)
        reviewers = connection.execute("SELECT reviewer FROM claim_assessments").fetchall()
    assert [row[0] for row in reviewers] == ["Royston"]
