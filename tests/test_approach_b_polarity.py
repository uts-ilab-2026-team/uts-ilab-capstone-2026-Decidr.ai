"""Development regressions for employee propositions; no formal evaluation."""

import pytest
from streamlit.testing.v1 import AppTest

from decidr.approach_b import ConstrainedClaimParser, load_profile, run_approach_b
from decidr.config import PHASE2_DATA_DIR, PROJ_ROOT
from decidr.database import connect
from decidr.evidence_b import excluded_summary
from decidr.ingestion import ingest
from decidr.models import ClaimOutcome, ConfidenceLevel, EvidenceTarget

OBSERVED = "Can sales employees approve a 20% new-business discount without a manager?"
ANSWER = (
    "No. A 20% new-business discount is at or above the 15% policy threshold and therefore requires written approval from the Head of Finance & People Ops "
    "before the opportunity is marked Closed Won. The approval must also be recorded in CRM."
)


@pytest.fixture(scope="module")
def ledger(tmp_path_factory):
    if not PHASE2_DATA_DIR.is_dir():
        pytest.skip("Phase 2 corpus unavailable")
    path = tmp_path_factory.mktemp("polarity") / "ledger.sqlite3"
    ingest({"phase2": PHASE2_DATA_DIR}, path)
    return path


def assess(ledger, question, **updates):
    claim = ConstrainedClaimParser().parse_proposal(question).claims[0]
    claim = claim.model_copy(update={"atomicity_status": "confirmed", **updates})
    with connect(ledger) as connection:
        return run_approach_b(
            connection, question, claim,
            load_profile(PROJ_ROOT / "configs/approach_b_graph_llm.yaml"), "development-test",
        )


@pytest.mark.parametrize("question,expected", [
    (OBSERVED, ClaimOutcome.CONTRADICTED),
    ("A 20% new-business discount requires authorised approval.", ClaimOutcome.SUPPORTED),
    ("A 20% new-business discount does not require approval.", ClaimOutcome.CONTRADICTED),
    ("Sales employees may approve independently a 20% new-business discount.", ClaimOutcome.CONTRADICTED),
    ("Can sales employees approve a 20% new-business discount without managerial approval?", ClaimOutcome.CONTRADICTED),
    ("Can sales employees approve a 20% new-business discount without a manger?", ClaimOutcome.CONTRADICTED),
    ("Can sales employees approve a 20% new-business discount without the Head of Finance & People Ops?", ClaimOutcome.CONTRADICTED),
])
def test_current_policy_relative_to_employee_proposition(ledger, question, expected):
    result = assess(ledger, question)
    assert result.confirmed_atomic_claim == ConstrainedClaimParser().parse_proposal(question).claims[0].claim_text
    assert result.outcome == expected
    assert result.confidence == ConfidenceLevel.MODERATE
    decisive = result.supporting_evidence + result.contradicting_evidence
    assert len(decisive) == 1
    assert decisive[0]["source_id"] == "phase2:POL-01"
    assert not result.evidence_gaps
    if question == OBSERVED:
        assert result.safe_employee_guidance == ANSWER


def test_below_boundary_not_supported(ledger):
    question = "Discounts below 15% require Head of Finance approval."
    proposal = ConstrainedClaimParser().parse_proposal(question)
    assert proposal.requires_clarification  # Missing business scope.
    result = assess(ledger, question + " This is new-business.")
    assert result.outcome != ClaimOutcome.SUPPORTED
    assert not result.supporting_evidence


def test_actual_practice_and_recorded_state_do_not_inherit_policy(ledger):
    for question, target in [
        ("Do sales employees actually obtain approval for a 20% new-business discount?", EvidenceTarget.ACTUAL_PRACTICE),
        ("Is approval for a 20% new-business discount recorded in CRM?", EvidenceTarget.RECORDED_STATE),
    ]:
        proposal = ConstrainedClaimParser().parse_proposal(question)
        assert len(proposal.claims) == 1
        assert proposal.claims[0].evidence_target == target
        result = assess(ledger, question)
        assert result.outcome == ClaimOutcome.INSUFFICIENT
        assert not result.supporting_evidence


def test_manager_ambiguity_is_focused():
    proposal = ConstrainedClaimParser().parse_proposal(OBSERVED.replace("a manager", "my line manager"))
    assert proposal.requires_clarification
    assert "line manager" in proposal.clarification


def test_missing_crm_fields_do_not_reduce_rule_confidence(ledger, tmp_path):
    # Compare the full corpus (including missing CRM fields) with a policy-only ledger.
    result = assess(ledger, OBSERVED)
    path = tmp_path / "policy.sqlite3"
    with connect(ledger) as source, connect(path) as destination:
        source.backup(destination)
        destination.execute("DELETE FROM evidence_fts WHERE evidence_id IN (SELECT evidence_id FROM evidence WHERE source_id != 'phase2:POL-01')")
        destination.execute("DELETE FROM evidence WHERE source_id != 'phase2:POL-01'")
        destination.commit()
    policy_only = assess(path, OBSERVED)
    assert (result.outcome, result.confidence) == (policy_only.outcome, policy_only.confidence)


def test_streamlit_observed_result_has_bounded_excluded_examples(ledger):
    result = assess(ledger, OBSERVED)
    excluded = result.not_applicable_evidence
    assert excluded
    result.not_applicable_evidence = (excluded * 100)[:99]
    counts, examples = excluded_summary(result.not_applicable_evidence)
    assert counts and len(examples) == 10
    app = AppTest.from_file(str(PROJ_ROOT / "app/pages/10_Approach_B_Graph_and_LLM_Assistant.py"))
    app.session_state["approach_b_result"] = result
    app.session_state["approach_b_stage"] = "result"
    app.run()
    assert not app.exception
    assert [metric.value for metric in app.metric] == ["Contradicted", "Moderate confidence"]
    assert any(ANSWER in item.value for item in app.markdown)
    eligible_count = sum(len(items) for items in (result.supporting_evidence, result.contradicting_evidence, result.qualifying_evidence, result.contextual_evidence))
    assert len([e for e in app.expander if e.label == "View source details"]) == eligible_count + 10
    assert any(e.label == "Optional excluded examples (10)" for e in app.expander)
    assert all(not e.proto.expanded for e in app.expander)
    page = (PROJ_ROOT / "app/pages/10_Approach_B_Graph_and_LLM_Assistant.py").read_text()
    from decidr.employee_print import PRINT_CSS
    assert "PRINT_CSS" in page and "@media print" in PRINT_CSS


@pytest.mark.parametrize("amount,relation,eligible", [
    ("14.99", "below", False), ("15", "meets", True), ("20", "exceeds", True),
])
def test_thresholds_remain_separate(ledger, amount, relation, eligible):
    from decidr.query_b import threshold, threshold_comparison
    comparison = threshold_comparison(threshold(amount + "%"), threshold("15% or greater"))
    assert comparison["relationship"] == relation
    assert comparison["within_policy_range"] == eligible
    result = assess(ledger, f"Do I need approval for a {amount}% new-business discount?")
    assert result.query_conditions["user_threshold"]["value"] == amount
    assert result.threshold_reasoning["policy"] == {"value": "15", "operator": "ge"}
    assert result.threshold_reasoning["relationship"] == relation
    if eligible:
        assert f"A {amount}% new-business discount" in result.safe_employee_guidance
        assert result.safe_employee_guidance.startswith("Yes.")
    else:
        assert result.outcome == ClaimOutcome.INSUFFICIENT


@pytest.mark.parametrize("user,policy,contained", [
    ("15%", "greater than 15%", False),
    ("15%", "greater than or equal to 15%", True),
    ("greater than 15%", "15% or greater", True),
    ("15% or greater", "greater than 15%", False),
    ("14.99%", "less than 15%", True),
])
def test_open_and_closed_intervals(user, policy, contained):
    from decidr.query_b import threshold, threshold_comparison
    assert threshold_comparison(threshold(user), threshold(policy))["within_policy_range"] == contained


def test_candidate_match_is_reference_only(ledger):
    result = assess(ledger, OBSERVED)
    assert result.matched_candidate_claim
    assert result.query_conditions["user_threshold"] == {"value": "20", "operator": "eq"}
    assert "20%" in result.confirmed_atomic_claim
    assert result.threshold_reasoning["policy"]["value"] == "15"
    assert result.safe_employee_guidance == ANSWER
    original = "Do I need approval for a 23% new-business discount in Sydney on 2024-04-02 if prepaid?"
    proposal = ConstrainedClaimParser().parse_proposal(original)
    assert proposal.claims[0].claim_text == original
    assert proposal.claims[0].original_claim_text == original
    assert proposal.requires_clarification
    assert "in Sydney on 2024-04-02 if prepaid" in proposal.claims[0].conditions


@pytest.mark.parametrize("condition,polarity,verdict,prefix", [
    ("approval_required", "positive", "Supported", "Yes. "),
    ("permission_without_approval", "permission_without_approval", "Contradicted", "No. "),
    ("approval_required", "negative", "Contradicted", "Yes. "),
    ("permission_without_approval", "positive", "Supported", "No. "),
    ("declarative", "positive", "Supported", ""),
    ("approval_required", "positive", "Insufficient evidence", ""),
])
def test_yes_no_is_relative_to_question(condition, polarity, verdict, prefix):
    from decidr.query_b import direct_answer
    assert direct_answer(condition, polarity, verdict) == prefix


def test_no_divergence_without_applicable_evidence_and_no_phase1(ledger, tmp_path):
    path = tmp_path / "policy-only.sqlite3"
    with connect(ledger) as source, connect(path) as destination:
        source.backup(destination)
        destination.execute("DELETE FROM evidence_fts WHERE evidence_id IN (SELECT evidence_id FROM evidence WHERE source_id != 'phase2:POL-01')")
        destination.execute("DELETE FROM evidence WHERE source_id != 'phase2:POL-01'")
        destination.commit()
    result = assess(path, OBSERVED)
    assert not result.policy_practice_divergence
    assert not result.divergence_evidence
    from decidr.employee_print import employee_print_html
    assert "practice may differ" not in employee_print_html(result)
    result = assess(ledger, OBSERVED)
    assert all(item["source_id"].startswith("phase2:") for item in result.citations)


@pytest.mark.parametrize("question,proposition,verdict,prefix", [
    (OBSERVED, "Sales employees may approve a 20% new-business discount without authorised approval.", "Contradicted", "No."),
    ("Do I need approval for a 15% new-business discount?", "A 15% new-business discount requires authorised approval.", "Supported", "Yes."),
])
def test_exact_questions_apptest_and_print(ledger, monkeypatch, question, proposition, verdict, prefix):
    import decidr.config
    from decidr.employee_print import PRINT_CSS, employee_print_html
    monkeypatch.setattr(decidr.config, "DATABASE_PATH", ledger)
    app = AppTest.from_file(str(PROJ_ROOT / "app/pages/10_Approach_B_Graph_and_LLM_Assistant.py"))
    app.run()
    app.chat_input[0].set_value(question).run()
    assert not app.exception
    assert app.text_area[0].value == proposition
    next(button for button in app.button if button.label == "Confirm and assess").click().run()
    assert not app.exception
    result = app.session_state["approach_b_result"]
    assert result.confirmed_atomic_claim == proposition
    assert result.outcome.value == verdict
    assert result.safe_employee_guidance.startswith(prefix)
    assert [metric.value for metric in app.metric] == [verdict, "Moderate confidence"]
    printed = employee_print_html(result)
    assert verdict in printed and "Moderate confidence" in printed
    assert "Co..." not in printed and "Mo..." not in printed
    assert "Responsible role identified in the cited policy" in printed
    for forbidden in ("Source Register", "Claims and Retrieval", "Graph and provenance", "Advanced technical details", "Download technical audit", "deterministic_rule_trace", "assessment_provenance"):
        assert forbidden not in printed
    assert 'break-inside: avoid' in PRINT_CSS and '@page { size: A4' in PRINT_CSS
    assert 'stSidebar' in PRINT_CSS and 'stChatInput' in PRINT_CSS


def test_compound_and_negative_questions_do_not_guess_yes_no():
    from decidr.query_b import question_condition
    for question in (
        "Do I need approval for a 15% new-business discount or can I close now?",
        "Can sales employees not approve a 20% new-business discount without a manager?",
        "What approval is needed for a 20% new-business discount?",
    ):
        assert question_condition(question) == "declarative"
