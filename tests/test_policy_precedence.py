"""Supplied facet judgements exercise precedence; no entailment is inferred."""

from dataclasses import replace
from datetime import date

from framework import CONFIG_PATH
from framework.config import GraphCredibilityConfig
import pytest
from test_assessment_adapter import CLAIM, DAY, FACET, make_item

from decidr.assessment_adapter import assess_prepared_facet


def pair(name, stance, kind="policy", **changes):
    item, passage = make_item(name, stance)
    summary = kind != "policy"
    item = replace(
        item,
        source_class=kind if summary else "approved_policy",
        source=item.source.model_copy(update={
            "source_type": "organisational_information" if summary else "policy",
        }),
        evidence_target="formal_rule", target_basis="Synthetic supplied facet comparison.",
        **changes,
    )
    return item, passage


def assess(pairs, target="formal_rule", threshold=None):
    config = GraphCredibilityConfig.load(CONFIG_PATH)
    if threshold is not None:
        config = replace(config, materiality_threshold=threshold)
    return assess_prepared_facet(
        claim_text=CLAIM, facet=FACET, as_of=DAY,
        prepared=[i for i, _ in pairs], evidence=[p for _, p in pairs],
        config=config, assessment_target=target,
    )


@pytest.mark.parametrize("summary", ["role_description", "decision_table"])
@pytest.mark.parametrize("stance,outcome", [("support", "Supported"), ("contradict", "Contradicted")])
def test_policy_governs_and_conflicting_summary_remains_cited(summary, stance, outcome):
    opposite = "contradict" if stance == "support" else "support"
    policy = pair("policy", stance)
    other = pair("summary", opposite, summary)
    result = assess([other, policy])
    assert result.assessment.formal_outcome == outcome
    assert result.inputs[0].edge_id is None
    assert result.inputs[0].interpretation.citations == other[0].interpretation.citations
    assert result.inputs[0].interpretation.stance == opposite
    assert "Policy precedence" in result.inputs[0].reasons[0]
    assert result.assessment.related_qualifiers
    assert "CORPUS_POLICY_PRECEDENCE_V1" in result.assessment.rules_applied
    assert assess([policy, other]).assessment.formal_outcome == outcome


@pytest.mark.parametrize("updates", [
    {"effective_start_date": date(2027, 1, 1)},
    {"effective_start_date": None},
    {"effective_end_date": date(2026, 1, 2)},
    {"superseded_date": DAY},
    {"lifecycle_status": "draft"},
    {"approval_status": "Never approved"},
])
def test_ineligible_or_undated_policy_cannot_displace_summary(updates):
    item, passage = pair("policy", "support")
    item = replace(item, source=item.source.model_copy(update=updates))
    result = assess([(item, passage), pair("summary", "contradict", "role_description")])
    assert result.inputs[1].edge_id is not None
    assert "CORPUS_POLICY_PRECEDENCE_V1" not in result.assessment.rules_applied


@pytest.mark.parametrize("field", ["scope_matches", "temporal_matches", "authority_verified"])
def test_unverified_policy_does_not_displace_summary(field):
    result = assess([pair("policy", "support", **{field: None}),
                     pair("summary", "contradict", "decision_table")])
    assert result.inputs[1].edge_id is not None


def test_nonmaterial_policy_does_not_displace_summary():
    result = assess([pair("policy", "support", directness=0, specificity=0, completeness=0),
                     pair("summary", "contradict", "decision_table")], threshold=0.7)
    assert result.inputs[1].edge_id is not None


def test_conflicting_policies_are_not_resolved_by_type_precedence():
    result = assess([pair("a", "support"), pair("b", "contradict"),
                     pair("summary", "contradict", "decision_table")])
    assert all(i.edge_id is not None for i in result.inputs)
    assert result.assessment.formal_outcome == "Contested"


def test_compatible_summary_is_not_excluded():
    result = assess([pair("policy", "support"), pair("summary", "support", "role_description")])
    assert all(i.edge_id is not None for i in result.inputs)


def test_procedure_is_not_treated_as_disposable_summary():
    item, passage = pair("procedure", "contradict")
    item = replace(item, source_class="approved_process",
                   source=item.source.model_copy(update={"source_type": "procedure"}))
    result = assess([pair("policy", "support"), (item, passage)])
    assert result.inputs[1].edge_id is not None


def test_precedence_disposition_is_in_serialized_response():
    from decidr.assessment_response import serialize_facet_assessment
    result = assess([pair("policy", "support"), pair("summary", "contradict", "decision_table")])
    payload = serialize_facet_assessment(result)
    assert payload["inputs"][1]["admitted_to_framework"] is False
    assert payload["inputs"][1]["interpretation"]["citations"]
    assert payload["assessment"]["related_qualifiers"]
    assert payload["assurance"]["authority_verification"] == "caller_declared_not_independently_verified"


def test_observed_input_is_not_displaced():
    item, passage = pair("observation", "contradict", "role_description")
    item = replace(item, interpretation=item.interpretation.model_copy(update={"mode": "observed"}),
                   evidence_target="underlying_event")
    # Use the legacy route to verify precedence is not applied across targets.
    items = [pair("policy", "support"), (item, passage)]
    items = [(replace(i, evidence_target="unspecified"), p) for i, p in items]
    result = assess(items, target="unspecified")
    assert all(i.edge_id is not None for i in result.inputs)
    assert "CORPUS_POLICY_PRECEDENCE_V1" not in result.assessment.rules_applied
