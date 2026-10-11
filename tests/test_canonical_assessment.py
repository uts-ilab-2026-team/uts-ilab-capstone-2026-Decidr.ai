from copy import deepcopy
from datetime import date
import json

import pytest

from decidr.canonical_assessment import canonical_assessment, processing_failure
from decidr.retrieval_models import Evidence, Source


def component(identifier="c1", text="Orders above 42 units require manager approval.", **changes):
    return {
        "id": identifier,
        "text": text,
        "claim_quote": text,
        "entities": ["orders"],
        "predicate": "require approval",
        "polarity": "positive",
        "quantities": [{"value": "42", "unit": "units", "comparator": "gt"}],
        "scope": ["orders"],
        "temporal": "currently",
        "modality": "required",
        **changes,
    }


def fixture(text="Orders above 42 units require manager approval.", **source_changes):
    source = Source(
        source_id="s",
        title="Requirements",
        original_file_path="rules.txt",
        source_type="policy",
        checksum="a" * 64,
        ingestion_status="ingested",
        creation_date=date(2025, 1, 1),
        author_or_system="Operations",
        lifecycle_status="current",
        **source_changes,
    )
    passage = Evidence(
        evidence_id="e",
        source_id="s",
        source_type=source.source_type,
        text=text,
        locator="section:requirements",
        extraction_method="test",
    )
    return {"e": passage}, {"s": source}


def finding(relationship="supports", **changes):
    return {
        "component_id": "c1",
        "evidence_id": "e",
        "source_id": "s",
        "quotation": "Orders above 42 units require manager approval.",
        "relationship": relationship,
        "reason": "The cited requirement establishes the stated rule.",
        "scope_fit": "yes",
        "time_fit": "yes",
        "directness": "direct",
        "limitations": [],
        "basis": "direct_statement",
        **changes,
    }


def assess(
    findings=None,
    components=None,
    target="formal_requirement",
    evidence=None,
    sources=None,
    **changes,
):
    default_evidence, default_sources = fixture()
    interpretation = {
        "target": target,
        "components": components or [component()],
        "ambiguities": [],
        "search_queries": ["order approval requirement"],
        **changes,
    }
    return canonical_assessment(
        interpretation,
        {
            "findings": findings if findings is not None else [finding()],
            "unresolved_questions": [],
        },
        evidence if evidence is not None else default_evidence,
        sources if sources is not None else default_sources,
        date(2026, 4, 1),
    )


@pytest.mark.parametrize("target", ["formal_requirement", "formal_authority"])
@pytest.mark.parametrize(
    "approval_status",
    [
        "Not approved",
        "Not yet formally approved",
        "Unapproved",
        "Pending",
        "Pending approval",
        "Approval is pending",
        "Awaiting sign-off",
        "Draft",
        "Withdrawn",
        "Approved; not approved",
    ],
)
def test_negative_or_pending_own_approval_blocks_current_formal_source(target, approval_status):
    evidence, sources = fixture(approval_status=approval_status)
    result = assess(target=target, evidence=evidence, sources=sources)
    assert result["overall_outcome"] == "Insufficient evidence"
    rejected = result["components"][0]["findings"][0]
    assert rejected["relationship"] == "context"
    assert any("approval status" in reason for reason in rejected["exclusion_reasons"])


@pytest.mark.parametrize(
    "approval_status",
    [
        None,
        "Unknown",
        "Not recorded",
        "Approved; review pending",
        "Approved (see REG-981 Not approved)",
    ],
)
def test_unknown_or_external_approval_status_is_not_a_negative_assertion(approval_status):
    evidence, sources = fixture(approval_status=approval_status)
    result = assess(evidence=evidence, sources=sources)
    assert result["overall_outcome"] == "Supported"
    assert result["components"][0]["findings"][0]["exclusion_reasons"] == []


def test_one_canonical_outcome_citations_graph_and_exposed_confidence():
    result = assess()
    assert result["processing"]["status"] == "assessed"
    assert result["overall_outcome"] == result["components"][0]["outcome"] == "Supported"
    assert result["citations"][0]["start"] == 0
    assert result["citations"][0]["locator"] == "section:requirements"
    assert result["evidence_relations"][0]["relationship"] == "supports"
    assert result["evidence_relations"][0]["inferential"] is True
    confidence = result["confidence"]
    assert 0 <= confidence["score"] <= 100
    assert confidence["calibrated"] is False
    assert sum(confidence["weights"].values()) == pytest.approx(1)
    assert "not probability" in confidence["meaning"]
    factors = confidence["components"][0]["factors"]
    assert confidence["score"] == round(
        100 * sum(confidence["weights"][k] * v for k, v in factors.items())
    )


def test_explicit_contradiction_can_have_equal_confidence_to_support():
    support, contradiction = assess(), assess([finding("contradicts")])
    assert contradiction["overall_outcome"] == "Contradicted"
    assert contradiction["confidence"]["score"] == support["confidence"]["score"]


@pytest.mark.parametrize(
    "relations,expected",
    [
        (["supports", "unresolved"], "Partially supported"),
        (["supports", "qualifies"], "Partially supported"),
        (["supports", "contradicts"], "Contradicted"),
        (["supports", "supports"], "Supported"),
        (["unresolved", "context"], "Insufficient evidence"),
    ],
)
def test_conjunction_never_hides_unanswered_or_contradicted_components(relations, expected):
    result = assess(
        [finding(relationship=r, component_id=f"c{i}") for i, r in enumerate(relations)],
        [component(identifier=f"c{i}") for i in range(2)],
    )
    assert result["overall_outcome"] == expected
    assert len(result["components"]) == 2


def test_within_component_conflict_and_interpretation_ambiguity_remain_visible():
    result = assess([finding(), finding("contradicts")])
    assert result["overall_outcome"] == "Conflicting evidence"
    ambiguous = assess(ambiguities=["It is unclear whether the claim covers renewals."])
    assert ambiguous["overall_outcome"] == "Partially supported"
    assert ambiguous["confidence"]["score"] < assess()["confidence"]["score"]
    assert ambiguous["unresolved_questions"]


@pytest.mark.parametrize("fit", ["scope_fit", "time_fit"])
def test_uncertain_contradiction_is_not_partial_support(fit):
    result = assess([finding("contradicts", **{fit: "unknown"})])
    assert result["overall_outcome"] == "Insufficient evidence"
    item = result["components"][0]["findings"][0]
    assert item["original_relationship"] == "contradicts"
    assert item["relationship"] == "unresolved"
    assert result["unresolved_questions"]


def test_sole_accuracy_challenge_does_not_count_as_positive_support():
    text = '{"quantity": "240", "notes": "Typo? This should perhaps be 24."}'
    evidence, sources = fixture(text=text)
    result = assess(
        [
            finding(
                "qualifies",
                quotation=text,
                reason="The note questions the recorded amount; it does not validate either value.",
            )
        ],
        target="value_accuracy",
        evidence=evidence,
        sources=sources,
    )
    assert result["overall_outcome"] == "Insufficient evidence"
    assert result["components"][0]["findings"][0]["relationship"] == "qualifies"
    assert result["confidence"]["components"][0]["factors"]["coverage"] == 0
    assert result["unresolved_questions"]
    mixed = assess([finding(), finding("qualifies")])
    assert mixed["overall_outcome"] == "Partially supported"


@pytest.mark.parametrize(
    "change",
    [
        {"quotation": "invented"},
        {"evidence_id": "missing"},
        {"source_id": "wrong"},
        {"component_id": "missing"},
        {"relationship": "similar"},
        {"scope_fit": "probably"},
        {"basis": "provider_confidence"},
    ],
)
def test_invalid_model_output_is_failure_without_outcome_or_score(change):
    result = assess([finding(**change)])
    assert result["processing"]["status"] == "failed"
    assert result["processing"]["code"] == "invalid_model_output"
    assert result["overall_outcome"] is None
    assert result["confidence"]["score"] is None


def test_provider_offsets_are_reconstructed_and_real_evidence_gap_is_distinct():
    result = assess([finding(start=500, end=999, locator="invented locator")])
    assert result["citations"][0]["start"] == 0
    gap = assess([])
    assert gap["processing"]["status"] == "assessed"
    assert gap["overall_outcome"] == "Insufficient evidence"
    assert isinstance(gap["confidence"]["score"], int)
    assert assess(evidence={})["processing"]["code"] == "empty_corpus"
    assert (
        processing_failure("provider_unavailable", "No local provider.")["confidence"]["score"]
        is None
    )


@pytest.mark.parametrize(
    "source_changes",
    [
        {"creation_date": date(2027, 1, 1)},
        {"effective_start_date": date(2027, 1, 1)},
        {"effective_end_date": date(2026, 1, 1)},
        {"lifecycle_status": "superseded"},
        {"lifecycle_status": "draft"},
        {"metadata_conflicts": [{"field": "version"}]},
    ],
)
def test_stale_future_draft_or_conflicted_sources_cannot_establish_current_requirement(
    source_changes,
):
    evidence, sources = fixture()
    sources["s"] = sources["s"].model_copy(update=source_changes)
    result = assess(evidence=evidence, sources=sources)
    assert result["overall_outcome"] == "Insufficient evidence"
    assert result["evidence_relations"][0]["relationship"] == "context"
    assert result["components"][0]["findings"][0]["exclusion_reasons"]


def test_review_date_does_not_expire_policy_and_historical_applicability_uses_claim_date():
    text = "Review date: 2025-02-01. Orders above 42 units require manager approval."
    evidence, sources = fixture(text=text)
    assert assess(evidence=evidence, sources=sources)["overall_outcome"] == "Supported"
    sources["s"] = sources["s"].model_copy(
        update={
            "lifecycle_status": "superseded",
            "superseded_date": date(2026, 2, 1),
            "effective_start_date": date(2025, 1, 1),
            "effective_end_date": date(2026, 1, 31),
        }
    )
    result = assess(
        target="historical_state",
        components=[component(temporal="as of 2025-09-01")],
        evidence=evidence,
        sources=sources,
    )
    assert result["overall_outcome"] == "Supported"


@pytest.mark.parametrize(
    "field,value",
    [("scope_fit", "no"), ("time_fit", "no"), ("scope_fit", "unknown"), ("time_fit", "unknown")],
)
def test_applicability_cannot_be_overridden_by_provider_support_label(field, value):
    result = assess([finding(**{field: value})])
    assert result["overall_outcome"] != "Supported"
    assert result["components"][0]["findings"][0]["original_relationship"] == "supports"


def test_current_practice_requires_observed_evidence_not_procedure_and_proposals_are_not_completion():
    evidence, sources = fixture()
    sources["s"] = sources["s"].model_copy(update={"source_type": "procedure"})
    result = assess(target="current_state", evidence=evidence, sources=sources)
    assert result["overall_outcome"] == "Insufficient evidence"
    row = json.dumps(
        {"task_id": "MIG-908", "status": "proposed", "task": "Migrate requests to Atlas"}
    )
    evidence["e"] = evidence["e"].model_copy(update={"text": row, "source_type": "project_tasks"})
    sources["s"] = sources["s"].model_copy(update={"source_type": "project_tasks"})
    result = assess(
        [finding(quotation=row, basis="recorded_action")],
        components=[component(text="Requests are currently managed in Atlas.")],
        target="current_state",
        evidence=evidence,
        sources=sources,
    )
    assert result["overall_outcome"] == "Insufficient evidence"
    complete = row.replace("proposed", "completed")
    evidence["e"] = evidence["e"].model_copy(update={"text": complete})
    assert (
        assess(
            [finding(quotation=complete, basis="recorded_action")],
            target="current_state",
            evidence=evidence,
            sources=sources,
        )["overall_outcome"]
        == "Supported"
    )


def test_approval_action_and_bare_value_do_not_validate_accuracy_or_authority():
    for basis in ("recorded_action", "direct_statement"):
        assert (
            assess([finding(basis=basis)], target="value_accuracy")["overall_outcome"]
            == "Insufficient evidence"
        )
    assert (
        assess([finding(basis="independent_validation")], target="value_accuracy")[
            "overall_outcome"
        ]
        == "Supported"
    )
    assert (
        assess([finding(basis="recorded_action")], target="formal_authority")["overall_outcome"]
        == "Insufficient evidence"
    )
    assert (
        assess([finding(basis="direct_statement")], target="formal_requirement")["overall_outcome"]
        == "Supported"
    )


def test_copies_repeated_paths_and_lineage_do_not_boost_confidence():
    evidence, sources = fixture()
    original = assess(evidence=evidence, sources=sources)
    sources["copy"] = sources["s"].model_copy(
        update={"source_id": "copy", "derived_from_source_id": "s"}
    )
    evidence["copy"] = evidence["e"].model_copy(
        update={"source_id": "copy", "evidence_id": "copy"}
    )
    findings = [finding(), finding(), finding(evidence_id="copy", source_id="copy")]
    result = assess(findings, evidence=evidence, sources=sources)
    assert result["confidence"]["score"] == original["confidence"]["score"]
    assert len(result["evidence_relations"]) == 2
    assert result["confidence"]["components"][0]["factors"]["independence"] == 0
    sources["s"] = sources["s"].model_copy(update={"derived_from_source_id": "copy"})
    cyclic = assess(findings, evidence=evidence, sources=sources)
    assert cyclic["processing"]["status"] == "assessed"
    assert cyclic["confidence"]["score"] == original["confidence"]["score"]


@pytest.mark.parametrize(
    "parents",
    [
        {"s": "a", "a": "b", "b": "a"},
        {"s": "a", "a": "unindexed-origin", "b": "unindexed-origin"},
    ],
)
def test_copy_descendants_share_cycle_or_unindexed_origin_without_confidence_inflation(parents):
    evidence, sources = fixture()
    template = sources["s"]
    findings = []
    for identifier, parent in parents.items():
        sources[identifier] = template.model_copy(
            update={
                "source_id": identifier,
                "derived_from_source_id": parent,
                "metadata_provenance": {
                    "independence_verified": "verified",
                    "independence_basis": "The documented original has an independently checked origin.",
                },
            }
        )
        text = f"Orders above 42 units require manager approval. Copy stored in {identifier}."
        evidence[identifier] = evidence["e"].model_copy(
            update={
                "source_id": identifier,
                "evidence_id": identifier,
                "text": text,
            }
        )
        findings.append(finding(source_id=identifier, evidence_id=identifier, quotation=text))
    single = assess(findings[:1], evidence=evidence, sources=sources)
    all_copies = assess(findings, evidence=evidence, sources=sources)
    assert all_copies["confidence"]["score"] == single["confidence"]["score"]
    basis = all_copies["confidence"]["components"][0]
    assert "1 documented origin group(s), 1 independently verified" in basis["basis"][0]
    assert basis["factors"]["independence"] == 0.5


def test_negation_and_unseen_numbers_domains_are_preserved_without_claim_specific_branches():
    text = "Chemical samples above 8.75 millilitres must not be shipped."
    evidence, sources = fixture(text=text)
    claim = component(
        text=text,
        polarity="negative",
        quantities=[{"value": "8.75", "unit": "millilitres", "comparator": "gt"}],
    )
    result = assess([finding(quotation=text)], [claim], evidence=evidence, sources=sources)
    assert result["overall_outcome"] == "Supported"
    assert result["interpreted_claim"]["components"][0]["polarity"] == "negative"
    assert result["citations"][0]["quotation"] == text


def test_malformed_unresolved_questions_are_processing_failure():
    evidence, sources = fixture()
    result = canonical_assessment(
        {"target": "event", "components": [component()], "ambiguities": []},
        {"findings": [finding()], "unresolved_questions": "not a list"},
        evidence,
        sources,
        date(2026, 4, 1),
    )
    assert result["processing"]["status"] == "failed"


def test_input_objects_are_not_mutated():
    evidence, sources = fixture()
    interpretation = {"target": "event", "components": [component()], "ambiguities": []}
    evaluated = {"findings": [finding()], "unresolved_questions": []}
    before = deepcopy((interpretation, evaluated))
    canonical_assessment(interpretation, evaluated, evidence, sources, date(2026, 4, 1))
    assert (interpretation, evaluated) == before


def test_summary_explains_decisive_evidence_and_retains_both_sides_of_conflict():
    supported_reason = "The current requirement names manager approval above the stated quantity."
    contradictory_reason = (
        "A second applicable passage expressly permits those orders without approval."
    )
    result = assess([finding(reason=supported_reason)])
    assert result["summary"] == f"Supported. Supporting evidence: {supported_reason}"
    conflicted = assess(
        [finding(reason=supported_reason), finding("contradicts", reason=contradictory_reason)]
    )
    assert conflicted["summary"].startswith("Conflicting evidence.")
    assert supported_reason in conflicted["summary"]
    assert contradictory_reason in conflicted["summary"]


def test_summary_explains_support_and_missing_component_without_repeating_entire_claim():
    claim = component("c2", "The manager approved the order before shipment.")
    reason = "The policy establishes the approval requirement."
    result = assess([finding(reason=reason)], [component(), claim])
    assert result["overall_outcome"] == "Partially supported"
    assert "2 components: 1 supported; 1 insufficient evidence" in result["summary"]
    assert reason in result["summary"]
    assert "No cited finding establishes or contradicts: " + claim["text"] in result["summary"]


def test_summary_does_not_present_excluded_support_as_established():
    evidence, sources = fixture(approval_status="Not approved")
    result = assess(
        [finding(reason="This policy establishes the current rule.")],
        evidence=evidence,
        sources=sources,
    )
    assert "Insufficient evidence." in result["summary"]
    assert "approval status is unapproved" in result["summary"]
    assert "This policy establishes" not in result["summary"]


def test_summary_preserves_qualification_and_interpretation_uncertainty():
    qualified = assess([finding("qualifies", reason="The note questions the recorded quantity.")])
    assert "Insufficient evidence." in qualified["summary"]
    assert "The note questions the recorded quantity." in qualified["summary"]
    ambiguous = assess(ambiguities=["The claim does not identify which order is meant."])
    assert ambiguous["overall_outcome"] == "Partially supported"
    assert "Supporting evidence:" in ambiguous["summary"]
    assert (
        "Interpretation remains uncertain: The claim does not identify which order is meant."
        in ambiguous["summary"]
    )


def test_contradiction_retains_unvalidated_counterevidence_and_lowers_disclosed_confidence():
    evidence, sources = fixture()
    uncertain_text = "An operational note may describe an exception; its applicability is unclear."
    evidence["uncertain"] = evidence["e"].model_copy(
        update={"evidence_id": "uncertain", "text": uncertain_text}
    )
    reason = (
        "The note's relationship to this requirement remains unresolved after semantic validation."
    )
    rejection = {
        "valid": False,
        "reason": reason,
        "original_proposal": {"relationship": "supports"},
    }
    uncertain = finding(
        "unresolved",
        evidence_id="uncertain",
        quotation=uncertain_text,
        reason=reason,
        basis="contextual",
        scope_fit="unknown",
        time_fit="unknown",
        directness="indirect",
        semantic_validation=rejection,
    )
    baseline = assess([finding("contradicts")], evidence=evidence, sources=sources)
    result = assess([finding("contradicts"), uncertain], evidence=evidence, sources=sources)
    assert result["overall_outcome"] == baseline["overall_outcome"] == "Contradicted"
    assert result["processing"]["status"] == "assessed"
    assert "Contradicting evidence:" in result["summary"]
    assert "Remaining uncertainty: " + reason in result["summary"]
    assert result["confidence"]["score"] < baseline["confidence"]["score"]
    factors = result["confidence"]["components"][0]["factors"]
    assert factors["interpretation_clarity"] == 0.5
    assert any(
        "1 unique unresolved" in basis for basis in result["confidence"]["components"][0]["basis"]
    )
    retained = result["components"][0]["findings"][1]
    assert retained["semantic_validation"] == rejection
    assert retained["admitted"] is False
    assert result["unresolved_questions"]
    # Repetition of the same unresolved passage does not invent more uncertainty.
    evidence["copy"] = evidence["uncertain"].model_copy(update={"evidence_id": "copy"})
    repeated = assess(
        [finding("contradicts"), uncertain, {**uncertain, "evidence_id": "copy"}],
        evidence=evidence,
        sources=sources,
    )
    assert repeated["confidence"] == result["confidence"]


def test_future_event_timestamp_blocks_support_but_pending_state_can_support_negation():
    text = json.dumps(
        {"task_id": "RUN-672", "status": "completed", "completion_date": "2027-01-01T09:00:00"}
    )
    evidence, sources = fixture(text=text)
    sources["s"] = sources["s"].model_copy(update={"source_type": "project_tasks"})
    result = assess(
        [finding(quotation=text, basis="recorded_action")],
        target="event",
        evidence=evidence,
        sources=sources,
    )
    assert result["overall_outcome"] == "Insufficient evidence"
    text = json.dumps({"task_id": "RUN-672", "status": "pending"})
    evidence["e"] = evidence["e"].model_copy(update={"text": text})
    negative = component(text="The migration is not completed.", polarity="negative")
    result = assess(
        [finding(quotation=text, basis="recorded_action")],
        [negative],
        target="event",
        evidence=evidence,
        sources=sources,
    )
    assert result["overall_outcome"] == "Supported"
    contradiction = assess(
        [finding("contradicts", quotation=text, basis="recorded_action")],
        target="event",
        evidence=evidence,
        sources=sources,
    )
    assert contradiction["overall_outcome"] == "Contradicted"


def dated_formal_fixture():
    evidence, sources = fixture(approval_status="Approved", effective_start_date=date(2025, 2, 3))
    headers = [
        {
            "key": "approval status",
            "value": "Approved",
            "quote": "- **Approval status:** Approved",
            "scope": "document_header",
            "source_id": "s",
        },
        {
            "key": "effective date",
            "value": "2025-02-03",
            "quote": "- **Effective date:** 2025-02-03",
            "scope": "document_header",
            "source_id": "s",
        },
    ]
    sources["s"].header_evidence = headers
    sources["s"].metadata_provenance = {
        "approval_status": "direct:markdown_metadata:approval status",
        "effective_date": "direct:markdown_metadata:effective date",
    }
    evidence["header"] = evidence["e"].model_copy(
        update={
            "evidence_id": "header",
            "locator": "document:header",
            "text": "\n".join(h["quote"] for h in headers) + "\n- **Review date:** 2025-04-01",
        }
    )
    return evidence, sources


def test_exact_formal_headers_resolve_unknown_time_with_trace_and_no_extra_findings():
    evidence, sources = dated_formal_fixture()
    original = finding(time_fit="unknown")
    before = deepcopy(original)
    result = assess([original], evidence=evidence, sources=sources)
    resolved = result["components"][0]["findings"][0]
    assert result["overall_outcome"] == "Supported"
    assert original == before
    assert resolved["original_time_fit"] == "unknown" and resolved["time_fit"] == "yes"
    derivation = resolved["temporal_derivation"]
    assert derivation["assessed_date"] == "2026-04-01"
    assert derivation["effective_start_date"] == "2025-02-03"
    assert len(resolved["citations"]) == len(result["citations"]) == 3
    for citation in derivation["citations"]:
        assert (
            evidence[citation["evidence_id"]].text[citation["start"] : citation["end"]]
            == citation["quotation"]
        )
        assert citation["source_id"] == "s"
    assert len(result["evidence_relations"]) == 1
    assert result["confidence"]["components"][0]["basis"][0].startswith(
        "1 unique admitted finding"
    )
    explicit = assess([finding(time_fit="yes")], evidence=evidence, sources=sources)
    assert explicit["citations"] == result["citations"]
    assert explicit["confidence"] == result["confidence"]


@pytest.mark.parametrize(
    "missing",
    [
        "provenance",
        "exact_passage",
        "approval",
        "source_binding",
        "date_value",
        "duplicate_header",
    ],
)
def test_temporal_derivation_requires_matching_exact_header_provenance(missing):
    evidence, sources = dated_formal_fixture()
    if missing == "provenance":
        sources["s"].metadata_provenance.clear()
    elif missing == "exact_passage":
        evidence.pop("header")
    elif missing == "approval":
        sources["s"].header_evidence = sources["s"].header_evidence[1:]
    elif missing == "source_binding":
        sources["s"].header_evidence[0]["source_id"] = "another-source"
    elif missing == "date_value":
        sources["s"].header_evidence[1]["value"] = "2025-02-04"
    else:
        sources["s"].header_evidence.append(deepcopy(sources["s"].header_evidence[1]))
    result = assess([finding(time_fit="unknown")], evidence=evidence, sources=sources)
    unresolved = result["components"][0]["findings"][0]
    assert unresolved["time_fit"] == "unknown"
    assert "temporal_derivation" not in unresolved
    assert result["overall_outcome"] == "Insufficient evidence"


@pytest.mark.parametrize(
    "changes",
    [
        {"effective_end_date": date(2025, 12, 31)},
        {"superseded_date": date(2025, 12, 31)},
        {"successor_source_id": "newer"},
        {"metadata_conflicts": [{"field": "effective_date", "reason": "Inconsistent headers"}]},
        {"lifecycle_status": "draft"},
        {"source_type": "interview"},
    ],
)
def test_temporal_derivation_keeps_inapplicable_or_nonformal_sources_unresolved(changes):
    evidence, sources = dated_formal_fixture()
    sources["s"] = sources["s"].model_copy(update=changes)
    result = assess([finding(time_fit="unknown")], evidence=evidence, sources=sources)
    assert result["components"][0]["findings"][0]["time_fit"] == "unknown"
    assert "temporal_derivation" not in result["components"][0]["findings"][0]


@pytest.mark.parametrize(
    "temporal,expected",
    [
        ("as of 2025-03-01", "yes"),
        ("as of 2024-03-01", "unknown"),
        ("as of 2027-03-01", "unknown"),
        ("before 2025-03-01", "unknown"),
        ("last year", "unknown"),
        ("2025-03-01 to 2025-05-01", "unknown"),
    ],
)
def test_temporal_derivation_respects_explicit_claim_dates_and_uncertainty(temporal, expected):
    evidence, sources = dated_formal_fixture()
    result = assess(
        [finding(time_fit="unknown")],
        [component(temporal=temporal)],
        evidence=evidence,
        sources=sources,
    )
    assert result["components"][0]["findings"][0]["time_fit"] == expected


def test_formal_headers_do_not_override_explicit_time_mismatch_or_resolve_other_targets():
    evidence, sources = dated_formal_fixture()
    rejected = assess([finding(time_fit="no")], evidence=evidence, sources=sources)
    assert rejected["components"][0]["findings"][0]["time_fit"] == "no"
    assert rejected["overall_outcome"] == "Insufficient evidence"
    event = assess(
        [finding(time_fit="unknown")], target="event", evidence=evidence, sources=sources
    )
    assert event["components"][0]["findings"][0]["time_fit"] == "unknown"
    scoped = assess(
        [finding(time_fit="unknown", scope_fit="unknown")], evidence=evidence, sources=sources
    )
    assert scoped["components"][0]["findings"][0]["time_fit"] == "yes"
    assert scoped["overall_outcome"] == "Insufficient evidence"


def test_full_header_ownership_metadata_cannot_establish_authority_but_rights_clause_can():
    text = "# Requirements\n- **Document owner:** Morgan\n- **Version:** 2.0\n- **Approval status:** Approved"
    evidence, sources = fixture(text=text)
    owner = assess(
        [finding(quotation=text)], target="formal_authority", evidence=evidence, sources=sources
    )
    assert owner["overall_outcome"] == "Insufficient evidence"
    assert "Document ownership" in owner["components"][0]["findings"][0]["exclusion_reasons"][0]
    text += "\nMorgan is authorised to adopt these requirements for the business."
    evidence["e"].text = text
    rights = assess(
        [finding(quotation=text)], target="formal_authority", evidence=evidence, sources=sources
    )
    assert rights["overall_outcome"] == "Supported"


@pytest.mark.parametrize("target", ["formal_requirement", "formal_authority"])
@pytest.mark.parametrize("relationship", ["supports", "contradicts"])
@pytest.mark.parametrize("basis", ["direct_statement", "reported_statement", "recorded_action"])
def test_interview_cannot_establish_formal_norm_even_if_model_calls_it_direct(
    target, relationship, basis
):
    text = "Role: Quality Lead. I approve the samples that come to me."
    evidence, sources = fixture(text=text)
    sources["s"].source_type = "interview"
    result = assess(
        [finding(relationship, quotation=text, basis=basis)],
        target=target,
        evidence=evidence,
        sources=sources,
    )
    retained = result["components"][0]["findings"][0]
    assert result["overall_outcome"] == "Insufficient evidence"
    assert retained["relationship"] == "context"
    assert retained["admitted"] is False
    assert retained["original_relationship"] == relationship
    assert retained["citations"][0]["quotation"] == text
    assert any(
        "Interview reports and recorded actions" in reason
        for reason in retained["exclusion_reasons"]
    )


@pytest.mark.parametrize("target", ["formal_requirement", "formal_authority"])
@pytest.mark.parametrize("basis", ["reported_statement", "recorded_action"])
def test_reported_or_performed_action_is_not_a_formal_norm_regardless_of_document_type(
    target, basis
):
    result = assess([finding(basis=basis)], target=target)
    assert result["overall_outcome"] == "Insufficient evidence"
    assert result["components"][0]["findings"][0]["relationship"] == "context"


@pytest.mark.parametrize("target", ["formal_requirement", "formal_authority", "event"])
@pytest.mark.parametrize("relationship", ["supports", "contradicts", "qualifies"])
def test_contextual_basis_cannot_be_inferential_despite_matching_role(target, relationship):
    result = assess(
        [
            finding(
                relationship,
                basis="contextual",
                limitations=["The role matches, but this is a separate process."],
            )
        ],
        target=target,
    )
    assert result["overall_outcome"] == "Insufficient evidence"
    retained = result["components"][0]["findings"][0]
    assert retained["relationship"] == "context" and not retained["admitted"]


def test_contextual_qualification_does_not_weaken_supported_rule_but_explicit_condition_does():
    background = finding(
        "qualifies", basis="contextual", reason="An unrelated process uses the same role."
    )
    result = assess([finding(), background])
    assert result["overall_outcome"] == "Supported"
    assert result["components"][0]["findings"][1]["relationship"] == "context"
    condition = {
        **background,
        "basis": "direct_statement",
        "reason": "The requirement expressly permits an emergency exception.",
    }
    qualified = assess([finding(), condition])
    assert qualified["overall_outcome"] == "Partially supported"
    assert qualified["components"][0]["findings"][1]["relationship"] == "qualifies"


def test_normative_guards_preserve_actual_policy_and_interview_reporting_targets():
    assert assess()["overall_outcome"] == "Supported"
    text = "I approve the samples that come to me."
    evidence, sources = fixture(text=text)
    sources["s"].source_type = "interview"
    result = assess(
        [finding(quotation=text, basis="reported_statement")],
        target="reported_statement",
        evidence=evidence,
        sources=sources,
    )
    assert result["overall_outcome"] == "Supported"


@pytest.mark.parametrize(
    "target,text",
    [
        (
            "formal_requirement",
            "The committee adopted the requirement that orders above 42 units require manager approval, effective 2025-02-03.",
        ),
        (
            "formal_authority",
            "The committee granted the Quality Lead authority to adopt laboratory handling rules, effective 2025-02-03.",
        ),
    ],
)
def test_adopted_norm_or_grant_in_meeting_record_is_direct_statement_not_ordinary_action(
    target, text
):
    evidence, sources = fixture(text=text)
    sources["s"].source_type = "meeting"
    documented = assess(
        [
            finding(
                quotation=text,
                basis="direct_statement",
                reason="The recorded decision explicitly states the adopted norm or grant and its effective date.",
            )
        ],
        [component(text=text)],
        target=target,
        evidence=evidence,
        sources=sources,
    )
    assert documented["overall_outcome"] == "Supported"
    assert documented["components"][0]["findings"][0]["admitted"] is True
    assert documented["citations"][0]["quotation"] == text
    action_only = assess(
        [
            finding(
                quotation=text,
                basis="recorded_action",
                reason="The record establishes only that a committee approval action occurred.",
            )
        ],
        [component(text=text)],
        target=target,
        evidence=evidence,
        sources=sources,
    )
    assert action_only["overall_outcome"] == "Insufficient evidence"
    assert action_only["components"][0]["findings"][0]["relationship"] == "context"


@pytest.mark.parametrize(
    "record",
    [
        {
            "record_id": "CASE-708",
            "approval_status": "not approved",
            "approval_record": "Recorded in approvals",
        },
        {"record_id": "ORDER-902", "approval_record": "Awaiting sign-off"},
        {"record_id": "BATCH-61", "approval_status": "pending"},
        {
            "record_id": "REQUEST-144",
            "approval_status": "approved",
            "approval_record": "Not approved",
        },
        {
            "record_id": "JOB-39",
            "approval_record": "REF-701",
            "approval_role": "Morgan",
            "approval_date": "2025-03-01",
        },
    ],
)
def test_completed_approval_cannot_be_supported_by_denied_pending_conflicting_or_reference_only_record(
    record,
):
    text = json.dumps(record)
    evidence, sources = fixture(text=text)
    claim = component(text="Morgan approved the request.", predicate="approved", quantities=[])
    result = assess(
        [finding(quotation=text, basis="recorded_action")],
        [claim],
        target="event",
        evidence=evidence,
        sources=sources,
    )
    retained = result["components"][0]["findings"][0]
    assert result["overall_outcome"] == "Insufficient evidence"
    assert retained["relationship"] == "context"
    assert retained["original_relationship"] == "supports"
    assert any("structured approval state" in reason for reason in retained["exclusion_reasons"])


@pytest.mark.parametrize(
    "claim",
    [
        component(
            text="The discount was 23%.",
            predicate="discount value",
            quantities=[{"value": "23", "unit": "%", "comparator": "eq"}],
        ),
        component(
            text="Morgan had not approved the request.",
            predicate="approved",
            polarity="negative",
            quantities=[],
        ),
        component(
            text="Morgan's approval was pending.", predicate="approval pending", quantities=[]
        ),
    ],
)
def test_approval_state_guard_does_not_reinterpret_quantity_negative_or_pending_components(claim):
    text = json.dumps({"record_id": "ORDER-316", "discount_pct": 23, "approval_status": "pending"})
    evidence, sources = fixture(text=text)
    result = assess(
        [finding(quotation=text, basis="recorded_action")],
        [claim],
        target="event",
        evidence=evidence,
        sources=sources,
    )
    assert result["overall_outcome"] == "Supported"
    assert result["components"][0]["findings"][0]["exclusion_reasons"] == []


def test_completed_approval_assertion_remains_admissible_and_declared_contradiction_is_preserved():
    text = json.dumps(
        {"record_id": "TASK-637", "approval_status": "approved", "approval_role": "Morgan"}
    )
    evidence, sources = fixture(text=text)
    claim = component(text="Morgan approved the request.", predicate="approved", quantities=[])
    result = assess(
        [finding(quotation=text, basis="recorded_action")],
        [claim],
        target="event",
        evidence=evidence,
        sources=sources,
    )
    assert result["overall_outcome"] == "Supported"
    denied = json.dumps({"record_id": "TASK-637", "approval_status": "denied"})
    evidence["e"].text = denied
    result = assess(
        [finding("contradicts", quotation=denied, basis="recorded_action")],
        [claim],
        target="event",
        evidence=evidence,
        sources=sources,
    )
    assert result["overall_outcome"] == "Contradicted"


@pytest.mark.parametrize("relationship", ["supports", "contradicts"])
@pytest.mark.parametrize("signed_key", ["signed_date", "contract_signed_date"])
@pytest.mark.parametrize("order", ["before", "after"])
def test_same_day_without_timestamps_cannot_establish_approval_signing_order(
    relationship, signed_key, order
):
    text = json.dumps(
        {
            "record_id": "CASE-742",
            "approval_status": "approved",
            "approval_date": "2025-03-17",
            signed_key: "2025-03-17",
        }
    )
    evidence, sources = fixture(text=text)
    claim = component(
        text=f"Morgan approved the request {order} the contract was signed.",
        predicate=f"approval {order} signing",
        quantities=[],
    )
    result = assess(
        [finding(relationship, quotation=text, basis="recorded_action")],
        [claim],
        target="event",
        evidence=evidence,
        sources=sources,
    )
    assert result["overall_outcome"] == "Insufficient evidence"
    assert result["components"][0]["findings"][0]["relationship"] == "context"
    assert any(
        "same date without timestamps" in reason
        for reason in result["components"][0]["findings"][0]["exclusion_reasons"]
    )


@pytest.mark.parametrize(
    "approval,signing",
    [
        ("2025-03-17", "2025-03-18"),
        ("2025-03-17T08:00:00", "2025-03-17T14:00:00"),
    ],
)
def test_distinct_dates_or_full_timestamps_are_not_blocked_by_same_day_guard(approval, signing):
    text = json.dumps(
        {
            "record_id": "REQUEST-689",
            "approval_status": "approved",
            "approval_date": approval,
            "signed_date": signing,
        }
    )
    evidence, sources = fixture(text=text)
    claim = component(
        text="Morgan approved the request before signing.",
        predicate="approval before signing",
        quantities=[],
    )
    result = assess(
        [finding(quotation=text, basis="recorded_action")],
        [claim],
        target="event",
        evidence=evidence,
        sources=sources,
    )
    assert result["overall_outcome"] == "Supported"


@pytest.mark.parametrize(
    "claim",
    [
        component(
            text="The recorded discount for the approval before signing was 23%.",
            predicate="discount value",
            quantities=[{"value": "23", "unit": "%", "comparator": "eq"}],
        ),
        component(
            text="Approval was pending before signing.",
            predicate="approval pending",
            quantities=[],
        ),
    ],
)
def test_same_day_guard_is_component_specific_and_preserves_pending_claims(claim):
    text = json.dumps(
        {
            "record_id": "ORDER-546",
            "discount_pct": 23,
            "approval_status": "pending",
            "approval_date": "2025-03-17",
            "signed_date": "2025-03-17",
        }
    )
    evidence, sources = fixture(text=text)
    result = assess(
        [finding(quotation=text, basis="recorded_action")],
        [claim],
        target="event",
        evidence=evidence,
        sources=sources,
    )
    assert result["overall_outcome"] == "Supported"


def test_exclusive_trigger_is_context_while_matching_inclusive_policy_still_assesses():
    claim_text = "Discounts of 27% or more require Compliance approval."
    role_text = "Compliance has approval authority above 27%."
    evidence, sources = fixture(text=claim_text)
    evidence["role"] = evidence["e"].model_copy(
        update={"evidence_id": "role", "source_id": "roles", "text": role_text}
    )
    sources["roles"] = sources["s"].model_copy(
        update={"source_id": "roles", "source_type": "organisational_information"}
    )
    claim = component(
        text=claim_text,
        predicate="require approval",
        quantities=[{"value": "27", "unit": "%", "comparator": "gte"}],
    )
    role = finding(
        quotation=role_text,
        evidence_id="role",
        source_id="roles",
        reason="This role passage describes an exclusive approval threshold.",
    )
    result = assess(
        [finding(quotation=claim_text), role], [claim], evidence=evidence, sources=sources
    )
    assert result["processing"]["status"] == "assessed"
    assert result["overall_outcome"] == "Supported"
    excluded = result["components"][0]["findings"][1]
    assert excluded["relationship"] == "context" and not excluded["admitted"]
    assert excluded["original_relationship"] == "supports"
    assert excluded["exclusion_reasons"]
    assert excluded["citations"][0]["quotation"] == role_text
    without_policy = assess([role], [claim], evidence=evidence, sources=sources)
    assert without_policy["processing"]["status"] == "assessed"
    assert without_policy["overall_outcome"] == "Insufficient evidence"
