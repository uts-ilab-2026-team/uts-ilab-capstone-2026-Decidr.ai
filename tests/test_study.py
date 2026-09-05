import json

import pytest

from decidr.models import AtomicClaim
from decidr.study import (
    comparison_claims,
    held_out_access_allowed,
    reviewer_packet,
    validate_portfolio,
    write_configured_study_materials,
    write_study_materials,
)


def _claim(identifier: int, split: str = "development") -> AtomicClaim:
    return AtomicClaim(
        claim_id=f"C{identifier}",
        subject="subject",
        predicate="requires",
        object="control",
        claim_type="control",
        claim_text=f"Atomic claim {identifier}.",
        atomicity_status="confirmed_atomic",
        evaluation_split=split,
    )


def test_study_readiness_requires_six_claims_and_two_held_out():
    too_small = validate_portfolio([_claim(1)])
    ready = validate_portfolio(
        [_claim(index, "held_out" if index >= 5 else "development") for index in range(1, 7)]
    )

    assert too_small.ready is False
    assert ready.ready is True
    assert ready.held_out_claims == 2


def test_atomicity_pending_blocks_study_readiness():
    claims = [_claim(index, "held_out" if index >= 5 else "development") for index in range(1, 7)]
    claims[0] = claims[0].model_copy(update={"atomicity_status": "potentially_compound"})

    result = validate_portfolio(claims)

    assert result.ready is False
    assert result.atomicity_pending == ("C1",)


def test_blind_packet_contains_no_automated_or_other_reviewer_outcomes():
    packet = reviewer_packet([_claim(1)], "reviewer-a")
    encoded = json.dumps(packet).casefold()

    assert packet["automated_outcomes_included"] is False
    assert packet["other_reviewer_judgements_included"] is False
    assert "evaluation_split" not in packet["claims"][0]
    assert "ambiguity_notes" not in packet["claims"][0]
    assert "automated assessment" not in encoded


def test_study_materials_require_two_real_distinct_reviewers(tmp_path):
    with pytest.raises(ValueError):
        write_study_materials([_claim(1)], "same-reviewer", "same-reviewer", tmp_path)


def test_study_materials_write_two_separate_packets(tmp_path):
    claims = [_claim(index, "held_out" if index >= 5 else "development") for index in range(1, 7)]

    manifest = write_study_materials(claims, "reviewer-a", "reviewer-b", tmp_path)

    assert manifest["packet_count"] == 2
    assert manifest["contains_automated_outcomes"] is False
    assert (tmp_path / "blind-review-reviewer-a.json").is_file()
    assert (tmp_path / "blind-review-reviewer-b.json").is_file()


def test_configured_packets_are_isolated_and_blind(tmp_path):
    claims = [_claim(index, "held_out" if index >= 5 else "development") for index in range(1, 7)]
    configuration = {
        "configuration_version": "1.1-final",
        "portfolio_status": "approved_and_frozen",
        "packet_generation_authorised": True,
        "held_out_access_status": "sealed",
        "reviewers": {"reviewer-a": "Royston", "reviewer-b": "Isanka"},
    }
    manifest = write_configured_study_materials(claims, configuration, tmp_path)

    assert manifest["packet_count"] == 2
    assert (tmp_path / "reviewer-a" / "blind-review-packet.json").is_file()
    assert (tmp_path / "reviewer-b" / "blind-review-packet.json").is_file()
    packet = json.loads((tmp_path / "reviewer-a" / "blind-review-packet.json").read_text())
    encoded = json.dumps(packet).casefold()
    for forbidden in ("evaluation_split", "challenge_characteristics", "verification_notes"):
        assert forbidden not in encoded


def test_held_out_comparison_unlocks_only_after_ruleset_freeze():
    claims = [_claim(1, "development"), _claim(2, "held_out")]
    sealed = {
        "reasoning_ruleset_status": "development_unfrozen",
        "held_out_access_status": "sealed",
    }
    unlocked = {
        "reasoning_ruleset_status": "approved_and_frozen",
        "held_out_access_status": "unlocked",
    }

    assert held_out_access_allowed(sealed) is False
    assert [claim.claim_id for claim in comparison_claims(claims, sealed)] == ["C1"]
    assert held_out_access_allowed(unlocked) is True
    assert [claim.claim_id for claim in comparison_claims(claims, unlocked)] == ["C1", "C2"]
