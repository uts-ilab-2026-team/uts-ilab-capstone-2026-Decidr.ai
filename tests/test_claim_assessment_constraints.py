"""Deterministic admission and schema regressions; no live model accuracy claims."""

from copy import deepcopy
from datetime import date

from pydantic import ValidationError
import pytest

from decidr.canonical_assessment import canonical_assessment
from decidr.claim_interpreter import (
    Interpretation,
    _interpretation_model,
    claim_evidence_exclusion,
    interpret_claim,
)
from decidr.retrieval_models import Evidence, Source


def component(text, value="23", unit="%", comparator="gte"):
    return {
        "id": "rule",
        "text": text,
        "claim_quote": text,
        "entities": [],
        "predicate": "is",
        "polarity": "positive",
        "quantities": [{"value": value, "unit": unit, "comparator": comparator}],
        "scope": [],
        "temporal": "current",
        "modality": "",
    }


def interpretation(text, target="formal_requirement", **quantity):
    return {
        "target": target,
        "components": [component(text, **quantity)],
        "ambiguities": [],
        "search_queries": [text],
    }


def finding(quote, relationship="contradicts", **changes):
    return {
        "component_id": "rule",
        "evidence_id": "passage",
        "source_id": "source",
        "quotation": quote,
        "relationship": relationship,
        "reason": "Proposed interpretation of the passage.",
        "scope_fit": "yes",
        "time_fit": "yes",
        "directness": "direct",
        "limitations": [],
        "basis": "direct_statement",
        **changes,
    }


@pytest.mark.parametrize(
    "claim",
    [
        "The current Legal-approval threshold for contract amendments is 23% and above.",
        "The previous purchase authorisation limit was EUR 720.",
        "The equipment consent threshold is six hours.",
        "The approval threshold for expense claims was USD 830.",
    ],
)
def test_normative_threshold_target_does_not_become_an_operational_state(claim):
    schema = _interpretation_model(claim).model_json_schema()
    assert schema["properties"]["target"]["const"] == "formal_requirement"
    assert schema["properties"]["components"]["maxItems"] == 20


@pytest.mark.parametrize(
    "claim",
    [
        "The configured approval threshold is 23%.",
        "The approval threshold setting is EUR 720.",
        "The recorded approval threshold is 23%.",
        "The approval threshold field is 23% and accurate.",
        "The interview says the approval threshold is 23%.",
        "According to the manager, the approval threshold is 23%.",
        "In practice, the approval threshold is 23%.",
        "The observed approval threshold is 23%.",
        "The manager approved a change whose threshold is 23%.",
        "The threshold is 23% and was raised yesterday.",
        "The current stock reorder threshold is 23%.",
        "The approval threshold is shown as 23% on the dashboard.",
    ],
)
def test_target_constraint_does_not_override_record_event_or_observed_assertions(claim):
    assert _interpretation_model(claim) is Interpretation


@pytest.mark.parametrize("quantifier", ["Every", "All", "Each"])
def test_universal_conjunction_keeps_both_predicates_scope_and_timing_verbatim(quantifier):
    claim = (
        f"{quantifier} purchase above EUR 720 receives Legal sign-off and is recorded "
        "before delivery."
    )
    model = _interpretation_model(claim)
    proposed = interpretation(claim, "observed_practice", value="720", unit="EUR", comparator="gt")
    assert model.model_validate(proposed).model_dump() == proposed
    changed = deepcopy(proposed)
    changed["components"][0]["text"] = "Purchases are subject to a sign-off process."
    with pytest.raises(ValidationError):
        model.model_validate(changed)
    split = deepcopy(proposed)
    split["components"].append({**split["components"][0], "id": "second"})
    with pytest.raises(ValidationError):
        model.model_validate(split)


class MockProvider:
    def __init__(self, *responses):
        self.responses = iter(responses)
        self.schemas = []

    def complete(self, schema, prompt):
        self.schemas.append(schema)
        return deepcopy(next(self.responses))


def verified():
    return {
        "component_checks": {"rule": {"valid": True, "reason": "The full claim is preserved."}},
        "omitted_claim_spans": [],
    }


def test_invalid_normative_target_is_repaired_and_provenance_is_not_conditional():
    claim = "The current approval threshold is 23% and above."
    wrong = interpretation(claim, "current_state")
    correct = interpretation(claim)
    provider = MockProvider(wrong, correct, verified())
    result = interpret_claim(claim, "2026-04-01", provider)
    assert result["target"] == "formal_requirement"
    assert result["semantic_validation"]["target_constraint_method"]
    assert "conditional_claim_method" not in result["semantic_validation"]
    assert "quantified_claim_method" not in result["semantic_validation"]


def test_quantified_route_has_its_own_provenance_and_keeps_actual_predicate():
    claim = "Every refund above 23% receives approval and is logged before payment."
    proposed = interpretation(claim, "observed_practice", comparator="gt")
    proposed["components"][0]["predicate"] = "receives approval and is logged before payment"
    result = interpret_claim(claim, "2026-04-01", MockProvider(proposed, verified()))
    assert result["components"][0]["text"] == claim
    assert result["semantic_validation"]["quantified_claim_method"]
    assert "conditional_claim_method" not in result["semantic_validation"]


@pytest.mark.parametrize("relationship", ["supports", "contradicts", "qualifies"])
@pytest.mark.parametrize(
    "quote",
    [
        "7% and above needs Legal sign-off. Below that you may close the order yourself.",
        "Orders above EUR 250 require authorisation before release.",
        "Access lasting over four hours must be approved by the supervisor.",
        "Consent is required before the request can be completed.",
    ],
)
def test_a_requirement_does_not_prove_actual_actions_even_in_a_message(quote, relationship):
    c = component("Every refund above 23% receives Legal sign-off and is recorded.")
    reason = claim_evidence_exclusion(c, finding(quote, relationship), "observed_practice")
    assert reason and "not a performed approval" in reason


@pytest.mark.parametrize(
    "quote",
    [
        "Orders need approval. The order was approved by the supervisor.",
        "Orders need approval. I approved the order before release.",
        "Orders need approval. The order received approval after release.",
        "Orders need approval. The supervisor approves every order herself.",
        "Orders need approval. Approval was never recorded for this order.",
        "Approval is required, but we bypass this on urgent orders.",
        "Approval is required. We do not follow that rule for emergency work.",
        "Approval is required, but compliance is inconsistent in practice.",
    ],
)
def test_mixed_rule_and_actual_action_passages_remain_available_to_semantic_review(quote):
    c = component("Every refund above 23% receives Legal sign-off.")
    assert claim_evidence_exclusion(c, finding(quote), "observed_practice") is None


@pytest.mark.parametrize(
    "claim,value,unit,quote",
    [
        (
            "The current consent threshold is 23% and above.",
            "23",
            "%",
            "The coordinator was replaced by the director as consent officer; the old process still names the coordinator.",
        ),
        (
            "The previous purchase approval threshold was EUR 720.",
            "720",
            "EUR",
            "The procurement team reports to Operations. The responsibility chart is outdated.",
        ),
        (
            "The approval threshold for equipment access is six hours.",
            "6",
            "hours",
            "The safety role changed and access now has a different approver.",
        ),
        (
            "The approval threshold is 23% and above.",
            "23",
            "%",
            "The officer handles purchases over EUR 900 and is named as discount approver in an outdated chart.",
        ),
    ],
)
def test_role_or_unrelated_quantity_cannot_contradict_a_quantitative_threshold(
    claim, value, unit, quote
):
    c = component(claim, value=value, unit=unit)
    assert "neither a comparable threshold" in claim_evidence_exclusion(
        c, finding(quote), "formal_requirement"
    )


@pytest.mark.parametrize(
    "quote",
    [
        "Approval is no longer required for these purchases.",
        "No supervisor consent is required for equipment access.",
        "These purchases do not require authorisation.",
        "The approval threshold was abolished.",
        "Purchases may be released without Legal sign-off.",
        "The applicable approval threshold is 31%.",
    ],
)
def test_explicit_rule_removal_or_a_comparable_quantity_can_be_counterevidence(quote):
    c = component("The current approval threshold is 23% and above.")
    assert claim_evidence_exclusion(c, finding(quote), "formal_requirement") is None


@pytest.mark.parametrize("target", ["event", "reported_statement", "value_accuracy"])
def test_quantitative_rule_guard_does_not_rewrite_other_assessment_targets(target):
    c = component("The transaction received approval for a 23% refund.")
    assert claim_evidence_exclusion(c, finding("Approval was declined."), target) is None


@pytest.mark.parametrize("target", ["formal_requirement", "formal_authority"])
def test_actor_conflict_in_a_quantity_qualified_rule_is_not_a_scalar_threshold_dispute(target):
    c = component(
        "Requests above USD 830 require Operations approval.",
        value="830",
        unit="USD",
        comparator="gt",
    )
    quote = "Only Legal may approve these requests; Operations cannot approve them."
    assert claim_evidence_exclusion(c, finding(quote), target) is None


def test_rule_change_event_does_not_need_a_performed_transaction_approval():
    c = component("The approval threshold was raised to 23%.", comparator="eq")
    quote = "The approval threshold was raised to 23% at the meeting."
    assert claim_evidence_exclusion(c, finding(quote, "supports"), "event") is None


def test_event_standards_preserve_formal_approval_kind_without_requiring_new_templates():
    from decidr.claim_interpreter import _TARGET_VERIFIER_STANDARDS

    standards = _TARGET_VERIFIER_STANDARDS["event"]
    assert "pilot, informal permission or trial is not formal adoption" in standards
    assert "Generic 'signed off' does not establish a specifically formal approval" in standards


def assess_component(
    c, quote, target, relationship="contradicts", source_type="internal_communication"
):
    source = Source(
        source_id="source",
        title="Record",
        original_file_path="record.txt",
        source_type=source_type,
        checksum="a" * 64,
        ingestion_status="ingested",
        creation_date=date(2025, 1, 1),
        author_or_system="Operations",
        lifecycle_status="current",
    )
    evidence = Evidence(
        evidence_id="passage",
        source_id="source",
        source_type=source_type,
        text=quote,
        locator="section:record",
        extraction_method="test",
    )
    return canonical_assessment(
        {"target": target, "components": [c], "ambiguities": [], "search_queries": []},
        {"findings": [finding(quote, relationship)], "unresolved_questions": []},
        {"passage": evidence},
        {"source": source},
        date(2026, 4, 1),
    )


def test_canonical_review_recomputes_numeric_exclusion_with_neutral_display():
    c = component("The current approval threshold is 23% and above.")
    result = assess_component(
        c, "The officer named in the approval chart is outdated.", "formal_requirement"
    )
    assert result["overall_outcome"] == "Insufficient evidence"
    f = result["components"][0]["findings"][0]
    assert f["relationship"] == "context"
    assert not f["admitted"]
    assert "Proposed interpretation" not in f["reason"]


def test_canonical_communications_requirement_is_not_observed_counterevidence():
    c = component("Every return above 23% receives approval and is logged before payment.")
    result = assess_component(c, "7% and above needs Legal sign-off.", "observed_practice")
    assert result["overall_outcome"] == "Insufficient evidence"
    assert result["components"][0]["findings"][0]["relationship"] == "context"


def test_categorical_removal_remains_an_admissible_formal_contradiction():
    c = component("The current approval threshold is 23% and above.")
    result = assess_component(
        c,
        "Approval is no longer required for these purchases.",
        "formal_requirement",
        source_type="policy",
    )
    assert result["overall_outcome"] == "Contradicted"


@pytest.mark.parametrize(
    "grounding",
    [
        "Whether the inspection was logged, no idea",
        "I don't know whether the parcel arrived.",
        "We cannot confirm that the safety check happened.",
        "It is unclear whether the refund was entered.",
        "I am not sure whether the signature was recorded.",
    ],
)
def test_uncertainty_is_not_counterproof_of_an_actual_event(grounding):
    c = component("Every inspection receives sign-off and is recorded before departure.")
    quote = "The interview concerned a particular inspection: " + grounding
    f = finding(quote, semantic_validation={"grounding_quote": grounding})
    reason = claim_evidence_exclusion(c, f, "observed_practice")
    assert reason and "uncertainty, not a contrary observation" in reason


@pytest.mark.parametrize(
    "quote",
    [
        "I don't know whether it was logged, but I saw the parcel leave without a signature.",
        "I don't know why approval was withheld.",
        "Approval was withheld. I am not sure why.",
        "The inspector confirmed no check was performed: I don't know why the team skipped it.",
        "I approved it and I don't know whether it was recorded.",
    ],
)
def test_uncertainty_does_not_erase_separate_actual_observations(quote):
    c = component("Every inspection receives sign-off and is recorded before departure.")
    assert claim_evidence_exclusion(c, finding(quote), "observed_practice") is None


def test_uncertainty_can_contradict_an_assertion_of_knowledge():
    c = component("Every supervisor knows whether inspections are logged.")
    assert (
        claim_evidence_exclusion(
            c, finding("I don't know whether inspections are logged."), "observed_practice"
        )
        is None
    )


@pytest.mark.parametrize(
    "quote",
    [
        "The record of what was agreed: get supervisor consent directly, enter the register afterwards.",
        "The team agreed to bypass the old route and seek permission afterwards.",
        "The decision was to obtain approval directly and log the inspection later.",
    ],
)
def test_agreed_instructions_do_not_establish_performed_practice(quote):
    c = component("Every inspection receives consent and is logged before departure.")
    reason = claim_evidence_exclusion(c, finding(quote), "observed_practice")
    assert reason and "agreed instruction" in reason


@pytest.mark.parametrize(
    "quote",
    [
        "The team agreed to obtain consent later. The inspection was signed off after departure.",
        "The decision was to seek consent directly. We followed that instruction for the inspection.",
        "The team agreed to enter approvals later, and they carried it out.",
    ],
)
def test_agreement_with_reported_execution_remains_available(quote):
    c = component("Every inspection receives consent and is logged before departure.")
    assert claim_evidence_exclusion(c, finding(quote), "observed_practice") is None


def test_instruction_can_establish_the_content_of_a_formal_decision():
    c = component("The approval threshold is 23% and above.")
    quote = "The committee agreed to require approval at 23% and above."
    assert claim_evidence_exclusion(c, finding(quote, "supports"), "formal_requirement") is None


def test_canonical_uncertainty_exclusion_keeps_citation_and_diagnostics():
    c = component("Every inspection receives consent and is logged before departure.")
    result = assess_component(c, "Whether the inspection was logged, no idea", "observed_practice")
    assert result["overall_outcome"] == "Insufficient evidence"
    f = result["components"][0]["findings"][0]
    assert f["relationship"] == "context" and not f["admitted"]
    assert f["citations"][0]["quotation"] == "Whether the inspection was logged, no idea"
    assert "uncertainty" in " ".join(f["exclusion_reasons"])


@pytest.mark.parametrize(
    "claim,value,unit,comparator,quote",
    [
        (
            "The approval threshold is 23% and above.",
            "23",
            "%",
            "gte",
            "Refunds at 31% and above require approval.",
        ),
        (
            "The approval threshold is 31% and above.",
            "31",
            "%",
            "gte",
            "Refunds at 23% and above require approval.",
        ),
        (
            "The authorisation limit is USD 420 and above.",
            "420",
            "USD",
            "gte",
            "Purchases of USD 610 or more need authorisation.",
        ),
        (
            "The consent threshold is six hours.",
            "6",
            "hours",
            "eq",
            "Access lasting eight hours requires consent.",
        ),
        (
            "The consent cutoff is below eight hours.",
            "8",
            "hours",
            "lt",
            "Access lasting below six hours requires consent.",
        ),
    ],
)
def test_scalar_cutoff_identity_is_not_supported_by_overlapping_ranges(
    claim, value, unit, comparator, quote
):
    from decidr.claim_interpreter import ProviderError, _validate_evidence_numbers

    c = component(claim, value, unit, comparator)
    f = finding(quote, "supports")
    assert "overlapping trigger range" in claim_evidence_exclusion(c, f, "formal_requirement")
    with pytest.raises(ProviderError, match="scalar approval cutoff"):
        _validate_evidence_numbers(c, f, {"text": quote})
    assert claim_evidence_exclusion(c, finding(quote, "qualifies"), "formal_requirement") is None
    result = assess_component(c, quote, "formal_requirement", "supports", source_type="policy")
    assert result["overall_outcome"] == "Insufficient evidence"
    assert result["components"][0]["findings"][0]["relationship"] == "context"


@pytest.mark.parametrize(
    "claim,value,unit,quote",
    [
        (
            "The consent threshold is six hours.",
            "6",
            "hours",
            "The consent threshold is 360 minutes.",
        ),
        (
            "The approval threshold is 23% for delivery within six days.",
            "23",
            "%",
            "Approval is required at 23% and above; processing takes eight days.",
        ),
        (
            "The approval threshold is 20%.",
            "20",
            "%",
            "Approval is required at one fifth of the amount.",
        ),
        ("The approval threshold is 23%.", "23", "%", "The rule is recorded in section 42."),
        (
            "The approval threshold is 23%.",
            "23",
            "%",
            "The manager also handles purchases of USD 420.",
        ),
    ],
)
def test_equivalence_and_unrelated_or_unrecognized_numbers_do_not_choose_a_relation(
    claim, value, unit, quote
):
    from decidr.claim_interpreter import _threshold_support_exclusion

    assert _threshold_support_exclusion(component(claim, value, unit), quote) is None


def test_subset_requirement_support_remains_valid_when_no_scalar_cutoff_is_asserted():
    from decidr.claim_interpreter import _validate_evidence_numbers

    c = component("Purchases of USD 420 and above require approval.", "420", "USD")
    quote = "Purchases of USD 210 and above require approval."
    f = finding(quote, "supports")
    assert claim_evidence_exclusion(c, f, "formal_requirement") is None
    _validate_evidence_numbers(c, f, {"text": quote})


def test_bound_verifier_cannot_reintroduce_disallowed_scalar_support():
    from decidr.claim_interpreter import (
        _evidence_verifier_model,
        _verification_relationship_constraints,
    )

    c = component("The approval threshold is 23% and above.")
    passages = {
        "different": {"text": "Approval is required at 31% and above."},
        "matching": {"text": "Approval is required at 23% and above."},
    }
    proposals = [
        {"component_id": "rule", "evidence_id": "different"},
        {"component_id": "rule", "evidence_id": "matching"},
    ]
    limits = _verification_relationship_constraints({"rule": c}, passages, proposals)
    assert limits == {0: ("contradicts", "qualifies", "context", "unresolved")}
    model = _evidence_verifier_model(["rule"], list(passages), 2, limits)
    check = {
        "fields_valid": True,
        "reason": "The cited rule has a different cutoff.",
        "grounding_quote": passages["different"]["text"],
        "expected_relationship": "supports",
    }
    output = {
        "finding_checks": {
            "0": check,
            "1": {**check, "grounding_quote": passages["matching"]["text"]},
        },
        "omitted_evidence": [],
    }
    with pytest.raises(ValidationError):
        model.model_validate(output)
    for relationship in limits[0]:
        output["finding_checks"]["0"]["expected_relationship"] = relationship
        assert (
            model.model_validate(output).finding_checks.check_1.expected_relationship == "supports"
        )


def test_scalar_verifier_constraint_keeps_approximate_values_for_semantic_review():
    from decidr.claim_interpreter import _threshold_support_exclusion

    c = component("The approval threshold is approximately 23%.", comparator="approx")
    assert _threshold_support_exclusion(c, "The threshold is 24%.") is None


def test_zero_is_a_real_scalar_cutoff_and_is_not_dropped():
    from decidr.claim_interpreter import _threshold_support_exclusion

    c = component("The approval threshold is 0% and above.", value="0")
    assert _threshold_support_exclusion(c, "Approval is required at 0% and above.") is None
    assert _threshold_support_exclusion(c, "Approval is required at 7% and above.")


def test_scalar_currency_support_cannot_assume_an_exchange():
    from decidr.claim_interpreter import _threshold_support_exclusion

    c = component("The approval threshold is EUR 420 and above.", "420", "EUR")
    assert "no exchange is assumed" in _threshold_support_exclusion(
        c, "Approval is required at USD 420 and above."
    )
    assert (
        _threshold_support_exclusion(
            c, "Approval is required at EUR 420 and above; unrelated travel allowance is USD 50."
        )
        is None
    )


def formal_event():
    c = component("The director formally approved the revised safety procedure in April.")
    c.update(predicate="formally approved", quantities=[])
    return c


@pytest.mark.parametrize(
    "quote",
    [
        "The director signed off on it at the time.",
        "The procedure has been used since April; the director approved the pilot.",
        "The Formal Compliance Director signed off on that version.",
        "The team received informal approval to try the procedure.",
    ],
)
def test_unspecified_signoff_or_titles_do_not_prove_specifically_formal_approval(quote):
    c = formal_event()
    assert "specifically claimed formal approval" in claim_evidence_exclusion(
        c, finding(quote, "supports"), "event"
    )
    for relation in ("qualifies", "context", "contradicts", "unresolved"):
        assert claim_evidence_exclusion(c, finding(quote, relation), "event") is None


@pytest.mark.parametrize(
    "quote",
    [
        "The director formally approved the revised safety procedure in April.",
        "The director ratified the revised safety procedure in April.",
        "The revised safety procedure was adopted in April by the director.",
        "Formal approval of the revised safety procedure was given by the director in April.",
    ],
)
def test_own_passage_explicit_formal_adoption_remains_eligible(quote):
    assert claim_evidence_exclusion(formal_event(), finding(quote, "supports"), "event") is None


def test_generic_approval_and_official_role_title_do_not_add_formality_to_the_claim():
    c = component("The official approved the revised procedure.")
    c.update(predicate="approved", quantities=[])
    assert (
        claim_evidence_exclusion(
            c, finding("The official signed off on the revision.", "supports"), "event"
        )
        is None
    )


def test_header_only_message_is_not_proof_of_completed_approval():
    quote = "**From:** Safety Director\n**To:** Site Lead\n**Timestamp:** 2025-04-03\n**Subject:** Revised safety procedure pilot"
    c = formal_event()
    assert "Communication headers" in claim_evidence_exclusion(
        c, finding(quote, "supports"), "event"
    )
    result = assess_component(c, quote, "event", "supports")
    assert result["overall_outcome"] == "Insufficient evidence"
    saved = result["components"][0]["findings"][0]
    assert saved["relationship"] == "context" and not saved["admitted"]
    assert saved["citations"][0]["quotation"] == quote


def test_communication_headers_can_establish_communication_sender_and_date():
    c = component("The director sent the procedure email on 3 April 2025.")
    c.update(predicate="sent", quantities=[])
    quote = "From: Safety Director\nTo: Site Lead\nDate: 2025-04-03\nSubject: Procedure pilot"
    assert claim_evidence_exclusion(c, finding(quote, "supports"), "event") is None
    assert assess_component(c, quote, "event", "supports")["overall_outcome"] == "Supported"


def test_formal_approval_verifier_support_constraints_apply_to_own_passage():
    from decidr.claim_interpreter import _verification_relationship_constraints

    c = formal_event()
    passages = {
        "header": {"text": "From: Director\nSubject: Procedure pilot"},
        "generic": {"text": "The director signed off on it."},
        "formal": {"text": "The director formally approved the procedure."},
    }
    proposed = [{"component_id": "rule", "evidence_id": eid} for eid in passages]
    constraints = _verification_relationship_constraints({"rule": c}, passages, proposed, "event")
    assert set(constraints) == {0, 1}
    assert all("supports" not in relationships for relationships in constraints.values())


def test_formal_approval_officer_title_does_not_add_formality_to_an_ordinary_event_claim():
    c = component("The Formal Approval Officer approved the revision.")
    c.update(predicate="approved", quantities=[])
    assert (
        claim_evidence_exclusion(
            c, finding("The officer signed off on the revision.", "supports"), "event"
        )
        is None
    )


def test_formal_approval_officer_title_does_not_establish_formality_in_evidence():
    quote = "The Formal Approval Officer signed off on the revision."
    assert "specifically claimed formal approval" in claim_evidence_exclusion(
        formal_event(), finding(quote, "supports"), "event"
    )


@pytest.mark.parametrize("prefix", ["- ", "+ ", "> ", "> - ", "1. ", "* "])
def test_markdown_message_headers_cannot_supply_substantive_approval(prefix):
    quote = "\n".join(
        prefix + line
        for line in [
            "**From:** Director",
            "Date: 2025-04-03",
            "Participants: Director and Site Lead",
            "Subject: Formal approval of revision",
        ]
    )
    assert "Communication headers" in claim_evidence_exclusion(
        formal_event(), finding(quote, "supports"), "event"
    )


@pytest.mark.parametrize(
    "quote",
    [
        "The Formal Approval Officer formally approved the procedure in April.",
        "The director granted formal approval for the procedure in April.",
        "Formal approval of the procedure was given by the director in April.",
        "- From: Director\n- Date: 2025-04-03\n\nI formally approved the revised safety procedure today.",
        "> Participants: Director\n> Decision: The director officially adopted the procedure.",
    ],
)
def test_actual_approval_clause_remains_eligible_with_a_title_or_surrounding_metadata(quote):
    assert claim_evidence_exclusion(formal_event(), finding(quote, "supports"), "event") is None


def test_signoff_in_an_official_role_does_not_make_the_event_formal():
    quote = "The director signed off on the revision as the Official Approval Officer."
    assert "specifically claimed formal approval" in claim_evidence_exclusion(
        formal_event(), finding(quote, "supports"), "event"
    )
    c = component(quote)
    c.update(predicate="signed off", quantities=[])
    assert (
        claim_evidence_exclusion(
            c, finding("The director signed off on the revision.", "supports"), "event"
        )
        is None
    )


def test_approval_as_an_official_procedure_refers_to_the_object_not_a_role():
    quote = "The director signed off on the revision as the official procedure."
    assert claim_evidence_exclusion(formal_event(), finding(quote, "supports"), "event") is None
