import json

import pytest

from decidr.approach_b import (
    BoundedGraphExpander,
    ConstrainedClaimParser,
    StrictCitationValidator,
    load_profile,
    run_approach_b,
)
from decidr.comparison import comparison_readiness
from decidr.config import PROJ_ROOT
from decidr.database import (
    connect,
    initialise_database,
    reset_test_records,
    save_claim_assessment,
    upsert_source,
    upsert_source_evidence,
)
from decidr.hybrid import HybridResult
from decidr.models import (
    AtomicClaim,
    ClaimAssessment,
    ClaimOutcome,
    ConfidenceLevel,
    Evidence,
    Source,
)


def test_parser_splits_rule_and_practice_without_inventing_period():
    proposal = ConstrainedClaimParser().parse_proposal(
        "What is the new-business 15% discount rule, and do employees follow it?"
    )

    assert len(proposal.claims) == 2
    assert {claim.evidence_target.value for claim in proposal.claims} == {
        "prescribed_rule",
        "routine_practice",
    }
    assert all(claim.applicable_start_date is None for claim in proposal.claims)
    assert proposal.clarification is not None


def test_parser_flags_missing_discount_scope_and_threshold():
    proposal = ConstrainedClaimParser().parse_proposal("Does a discount require approval?")

    assert "discount threshold" in proposal.ambiguities
    assert "deal scope" in proposal.ambiguities


def test_clear_discount_question_proposes_useful_atomic_claim():
    proposal = ConstrainedClaimParser().parse_proposal(
        "Do I need approval for a 15% new-business discount?"
    )
    claim = proposal.claims[0]
    assert proposal.requires_clarification is False
    assert claim.subject != claim.original_claim_text
    assert claim.subject == "A new-business deals discount of 15%"
    assert claim.predicate == "requires"
    assert claim.evidence_target.value == "prescribed_rule"


def test_typo_does_not_turn_raw_question_into_subject():
    proposal = ConstrainedClaimParser().parse_proposal("15% claim need approavl?")
    assert proposal.requires_clarification is True
    assert all(claim.subject != "15% claim need approavl?" for claim in proposal.claims)


def test_assessment_requires_confirmation(tmp_path):
    database = tmp_path / "ledger.sqlite3"
    initialise_database(database)
    proposal = ConstrainedClaimParser().parse_proposal(
        "Do I need approval for a 15% new-business discount?"
    )
    with connect(database) as connection, pytest.raises(ValueError, match="confirmed"):
        run_approach_b(connection, "question", proposal.claims[0], _profile(), "fixture")


def _profile():
    return {
        "approach_id": "approach_b_test",
        "configuration_version": "test",
        "embedding_model": "unused",
        "cross_encoder_model": "unused",
        "semantic_enabled": False,
        "llm_enabled": False,
    }


def _source(source_id: str, *, duplicate_group=None, path=None):
    return Source(
        source_id=source_id,
        metadata_notes="release=" + source_id.split(":", 1)[0],
        ingestion_status="ingested",
        title="Discount policy",
        original_file_path=path or f"/Users/example/private/{source_id}.md",
        source_type="policy",
        lifecycle_status="current",
        responsible_person_or_role="Head of Finance",
        duplicate_group=duplicate_group,
        checksum=("a" if source_id.endswith("1") else "b") * 64,
    )


def _evidence(evidence_id: str, source_id: str):
    return Evidence(
        evidence_id=evidence_id,
        source_id=source_id,
        locator="section:rule",
        text="A new-business discount of 15% requires written approval before Closed Won.",
        source_type="policy",
        extraction_method="fixture",
    )


def test_supported_result_has_citations_fallbacks_and_no_review_writes(tmp_path):
    database = tmp_path / "ledger.sqlite3"
    initialise_database(database)
    claim = (
        ConstrainedClaimParser()
        .parse_proposal("Do I need approval for a 15% new-business discount?")
        .claims[0]
        .model_copy(update={"atomicity_status": "user_confirmed"})
    )
    with connect(database) as connection:
        upsert_source(connection, _source("phase2:S1"))
        upsert_source_evidence(connection, "phase2:S1", [_evidence("E1", "phase2:S1")])
        before = connection.execute("SELECT COUNT(*) FROM claim_assessments").fetchone()[0]
        result = run_approach_b(connection, "question", claim, _profile(), "fixture")
        after = connection.execute("SELECT COUNT(*) FROM claim_assessments").fetchone()[0]
    assert result.outcome == ClaimOutcome.SUPPORTED
    assert result.citations[0]["evidence_id"] == "E1"
    assert result.retrieval_component_status["semantic"] == "disabled by configuration"
    assert result.retrieval_component_status["llm"] == "disabled by configuration"
    assert "/Users/" not in json.dumps(result.model_dump(mode="json"))
    assert before == after == 0
    assert "evaluation_split" not in json.dumps(result.model_dump(mode="json"))


def test_graph_expansion_does_not_multiply_duplicate_evidence(tmp_path):
    database = tmp_path / "ledger.sqlite3"
    initialise_database(database)
    with connect(database) as connection:
        for suffix in ("1", "2"):
            upsert_source(connection, _source(f"phase2:S{suffix}", duplicate_group="same"))
            upsert_source_evidence(
                connection, f"phase2:S{suffix}", [_evidence(f"E{suffix}", f"phase2:S{suffix}")]
            )
        seed = HybridResult("E1", "phase2:S1", "section:rule", "rule", 1, 1.0, 1, None)
        expanded = BoundedGraphExpander(connection).expand(
            AtomicClaim(
                claim_id="C",
                subject="s",
                predicate="p",
                object="o",
                claim_type="test",
                claim_text="test",
            ),
            [seed, seed],
        )
    assert [item["evidence_id"] for item in expanded].count("E2") == 1


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
        claim_id="C",
        subject="s",
        predicate="p",
        object="o",
        claim_type="test",
        claim_text="test",
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
    assert readiness.development_ready is False
    assert readiness.held_out_ready is False


def test_safe_reset_removes_only_test_namespace(tmp_path):
    from decidr.database import initialise_database, save_claim

    database = tmp_path / "ledger.sqlite3"
    initialise_database(database)
    claim = AtomicClaim(
        claim_id="C",
        subject="s",
        predicate="p",
        object="o",
        claim_type="test",
        claim_text="test",
    )
    with connect(database) as connection:
        save_claim(connection, claim)
        for reviewer in ("test:fixture", "Royston"):
            save_claim_assessment(
                connection,
                ClaimAssessment(
                    assessment_id=f"A-{reviewer}",
                    claim_id="C",
                    reviewer=reviewer,
                    outcome=ClaimOutcome.INSUFFICIENT,
                    confidence=ConfidenceLevel.LOWER,
                    uncertainty_explanation="gap",
                    explanation="test",
                    review_status="complete",
                ),
                [],
            )
        reset_test_records(connection)
        reviewers = connection.execute("SELECT reviewer FROM claim_assessments").fetchall()
    assert [row[0] for row in reviewers] == ["Royston"]


def _confirmed_discount(amount=15, **updates):
    return (
        ConstrainedClaimParser()
        .parse_proposal(f"Do I need approval for a {amount}% new-business discount?")
        .claims[0]
        .model_copy(update={"atomicity_status": "confirmed", **updates})
    )


def _crm(discount="18", stage="Closed Won", approval="Recorded in CRM", notes="", **extra):
    record = {
        "deal_id": "DEAL-test",
        "deal_type": "new-business",
        "discount_pct": discount,
        "stage": stage,
        "close_date": "2025-07-01",
        "approval_record": approval,
        "approval_role": "Head of Finance",
        "notes": notes,
        **extra,
    }
    return {
        "evidence_id": "CRM-E",
        "source_id": "phase2:CRM",
        "locator": "row:1",
        "text": json.dumps(record),
        "metadata": {"structured_metadata": {"record": record}},
    }


def _crm_source():
    return _source("phase2:CRM").model_copy(update={"source_type": "crm_records"})


@pytest.mark.parametrize("discount", ["0", "9", "10", "11", "", None, "150"])
def test_crm_threshold_eligibility(discount):
    from decidr.evidence_b import eligibility

    result = eligibility(_confirmed_discount(), _crm(discount=discount), _crm_source(), {})
    assert not result.eligible
    assert not result.checks["threshold"]


@pytest.mark.parametrize(
    "changes,dimension",
    [
        ({"stage": "Closed Lost"}, "event"),
        ({"notes": "Prepay renewal"}, "scope"),
        ({"deal_type": "renewal"}, "scope"),
        ({"close_date": ""}, "record_dates"),
    ],
)
def test_crm_scope_outcome_and_dates(changes, dimension):
    from decidr.evidence_b import eligibility

    result = eligibility(_confirmed_discount(), _crm(**changes), _crm_source(), {})
    assert not result.eligible
    assert not result.checks[dimension]


def test_temporal_eligibility_requires_contained_historical_period():
    from datetime import date
    from decidr.evidence_b import eligibility

    old = _source("phase2:POL-02").model_copy(
        update={
            "lifecycle_status": "superseded",
            "effective_start_date": date(2021, 6, 1),
            "successor_source_id": "phase2:POL-01",
        }
    )
    current = _source("phase2:POL-01").model_copy(
        update={"effective_start_date": date(2025, 3, 1)}
    )
    item = {"text": "Any discount of 10% or greater requires written approval before Closed Won."}
    sources = {"phase2:POL-01": current}
    assert not eligibility(_confirmed_discount(), item, old, sources).eligible
    historical = _confirmed_discount(
        10, applicable_start_date=date(2024, 1, 1), applicable_end_date=date(2024, 12, 31)
    )
    result = eligibility(historical, item, old, sources)
    assert result.eligible and result.historical
    crossing = historical.model_copy(update={"applicable_end_date": date(2025, 3, 1)})
    assert not eligibility(crossing, item, old, sources).eligible


def test_canonical_copy_and_historical_support_in_assessment(tmp_path):
    from datetime import date

    database = tmp_path / "canonical.sqlite3"
    initialise_database(database)
    with connect(database) as connection:
        for release in ("phase2", "phase2:copy"):
            # Both copies belong to the active modelling namespace.
            sid = f"{release}:POL-01"
            upsert_source(
                connection,
                _source(sid, duplicate_group="phase2:POL-01").model_copy(
                    update={"effective_start_date": date(2025, 3, 1)}
                ),
            )
            upsert_source_evidence(connection, sid, [_evidence(f"{release}-E", sid)])
        old = _source("phase2:POL-02").model_copy(
            update={
                "lifecycle_status": "superseded",
                "effective_start_date": date(2021, 6, 1),
                "successor_source_id": "phase2:POL-01",
            }
        )
        upsert_source(connection, old)
        upsert_source_evidence(
            connection,
            "phase2:POL-02",
            [
                _evidence("old-E", "phase2:POL-02").model_copy(
                    update={
                        "text": "Any new-business discount of 10% or greater requires written approval before Closed Won."
                    }
                )
            ],
        )
        current = run_approach_b(
            connection, "question", _confirmed_discount(), _profile(), "fixture"
        )
        assert len(current.supporting_evidence) == 1
        assert current.supporting_evidence[0]["source_id"].startswith("phase2:")
        assert current.dependency_duplication_notes
        assert all(i["source_id"] != "phase2:POL-02" for i in current.supporting_evidence)
        assert len(current.citations) == 1
        historical = run_approach_b(
            connection,
            "historical",
            _confirmed_discount(
                10, applicable_start_date=date(2024, 1, 1), applicable_end_date=date(2024, 12, 31)
            ),
            _profile(),
            "fixture",
        )
        assert historical.outcome == ClaimOutcome.SUPPORTED
        assert [i["source_id"] for i in historical.supporting_evidence] == ["phase2:POL-02"]


@pytest.mark.parametrize(
    "approval,notes,divergence",
    [
        ("Recorded outside CRM (Slack)", "Approval was recorded outside CRM", True),
        ("", "", False),
        ("None found", "", False),
    ],
)
def test_practice_divergence_does_not_contradict_rule(tmp_path, approval, notes, divergence):
    database = tmp_path / "practice.sqlite3"
    initialise_database(database)
    with connect(database) as connection:
        upsert_source(connection, _source("phase2:S1"))
        upsert_source_evidence(connection, "phase2:S1", [_evidence("E1", "phase2:S1")])
        upsert_source(connection, _crm_source())
        item = _crm(approval=approval, notes=notes)
        upsert_source_evidence(
            connection,
            "phase2:CRM",
            [
                Evidence(
                    evidence_id="CRM-E",
                    source_id="phase2:CRM",
                    locator="row:1",
                    text=item["text"],
                    source_type="crm_records",
                    extraction_method="fixture",
                    structured_metadata=item["metadata"]["structured_metadata"],
                )
            ],
        )
        result = run_approach_b(
            connection, "question", _confirmed_discount(), _profile(), "fixture"
        )
    assert result.outcome == ClaimOutcome.SUPPORTED
    assert not result.contradicting_evidence
    assert bool(result.policy_practice_divergence) == divergence
    assert bool(result.divergence_evidence) == divergence
    if divergence:
        from decidr.employee_print import employee_print_html
        assert result.divergence_evidence[0]["evidence_id"] == "CRM-E"
        assert "CRM-E" in employee_print_html(result)
        assert "outside CRM" in employee_print_html(result)
        assert all(result.divergence_evidence[0]["eligibility"]["checks"].values())
    assert len(result.supporting_evidence) == 1
    assert len(result.qualifying_evidence) == 1
    assert "{" not in result.qualifying_evidence[0]["excerpt"]
    assert not result.evidence_gaps
    assert "requires written approval before the opportunity is marked Closed Won" in result.safe_employee_guidance
    assert "Obtain written approval before the opportunity is marked Closed Won" in result.recommended_organisational_action


def test_employee_presentation_limits_and_gap_consistency():
    from types import SimpleNamespace
    from decidr.evidence_b import employee_evidence, excerpt, gap_summary, rule_fields

    result = SimpleNamespace(
        supporting_evidence=[{"id": n} for n in range(5)],
        contradicting_evidence=[],
        qualifying_evidence=[{"id": 5}],
        contextual_evidence=[{"id": 6}],
    )
    primary, additional = employee_evidence(result)
    assert len(primary) == 3
    assert len(additional) == 4
    assert "No material" in gap_summary([])
    assert "No material" not in gap_summary(["Missing approval information."])
    assert excerpt("a complete sentence with words", 18) == "a complete…"
    fields = rule_fields(
        "Any discount of 22% or greater requires written approval from the Finance Director before booking.\nApproval must be recorded in the ledger."
    )
    assert fields["approver"] == "the Finance Director"
    assert "22%" in fields["proposition"]
    assert fields["recording"] == "Approval must be recorded in the ledger."


def test_no_deprecated_streamlit_width_calls():
    assert not any(
        "use_container_width" in path.read_text() for path in (PROJ_ROOT / "app").rglob("*.py")
    )


def test_employee_page_uses_collapsed_disclosure(tmp_path):
    from streamlit.testing.v1 import AppTest

    database = tmp_path / "ui.sqlite3"
    initialise_database(database)
    with connect(database) as connection:
        upsert_source(connection, _source("phase2:S1"))
        upsert_source_evidence(connection, "phase2:S1", [_evidence("E1", "phase2:S1")])
        result = run_approach_b(
            connection, "question", _confirmed_discount(), _profile(), "fixture"
        )
    result.supporting_evidence = result.supporting_evidence * 5
    app = AppTest.from_file(str(PROJ_ROOT / "app/pages/10_Approach_B_Graph_and_LLM_Assistant.py"))
    app.session_state["approach_b_result"] = result
    app.session_state["approach_b_stage"] = "result"
    app.run()
    assert not app.exception
    labels = [item.label for item in app.expander]
    assert "Additional eligible evidence (2)" in labels
    assert "Excluded evidence with reasons (0)" in labels
    assert "Graph and provenance" in labels
    assert "Advanced technical details" in labels
    assert all(not item.proto.expanded for item in app.expander)


@pytest.mark.parametrize(
    "boundary,eligible",
    [
        ("15% or greater", True),
        ("above 15%", False),
        ("greater than 15%", False),
        ("greater than or equal to 15%", True),
        ("below 15%", False),
        ("15% or less", True),
    ],
)
def test_threshold_boundary_is_not_lexical_similarity(boundary, eligible):
    from decidr.evidence_b import eligibility

    item = {
        "text": f"Any new-business discount {boundary} requires written approval before Closed Won."
    }
    assert (
        eligibility(_confirmed_discount(), item, _source("phase2:POL-01"), {}).eligible == eligible
    )


def test_unestablished_organisation_or_extra_condition_is_ineligible():
    from decidr.evidence_b import eligibility

    item = {"text": _evidence("E", "phase2:S1").text}
    claim = _confirmed_discount(scope="Sydney sales team")
    assert not eligibility(claim, item, _source("phase2:S1"), {}).eligible
    claim = _confirmed_discount(conditions=["discount is 15%", "emergency exception"])
    assert not eligibility(claim, item, _source("phase2:S1"), {}).eligible


def test_formal_rule_cannot_establish_routine_practice():
    from decidr.evidence_b import eligibility
    from decidr.models import EvidenceTarget

    claim = _confirmed_discount(evidence_target=EvidenceTarget.ROUTINE_PRACTICE)
    result = eligibility(
        claim, {"text": _evidence("E", "phase2:S1").text}, _source("phase2:S1"), {}
    )
    assert not result.eligible
    assert not result.checks["target"]
