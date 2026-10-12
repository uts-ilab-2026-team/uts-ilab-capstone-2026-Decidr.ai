"""Mocked provider integration; these checks do not claim live model validation."""

from contextlib import closing
from copy import deepcopy
from datetime import date
import importlib
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

from decidr import general_assessment as general
from decidr.api.interpretation import InterpretationProposalRequest
from decidr.assessment_history import content_hash
from decidr.claim_interpreter import ProviderError
from decidr.retrieval_models import Evidence, Source

api = importlib.import_module("decidr.api.app")
CLAIM = "Orders above 42 units require manager approval."


def frozen_corpus():
    sources, evidence = {}, {}

    def add(eid, sid, text, kind="policy", **changes):
        if sid not in sources:
            sources[sid] = Source(
                source_id=sid,
                title=sid,
                original_file_path=sid + ".txt",
                source_type=kind,
                checksum="a" * 64,
                ingestion_status="ingested",
                lifecycle_status="current",
                creation_date=date(2025, 1, 1),
                author_or_system="Operations",
            )
        evidence[eid] = Evidence(
            evidence_id=eid,
            source_id=sid,
            source_type=kind,
            text=text,
            locator=eid,
            extraction_method="test",
            **changes,
        )

    add("rule", "orders", "Scope and requirements: " + CLAIM + " Exceptions follow.", paragraph=2)
    add("header", "orders", "Version 2. Effective from 2025-01-01.", paragraph=1)
    add(
        "conditions",
        "orders",
        "This rule applies to wholesale orders only; emergency exceptions require written reasons.",
        paragraph=3,
    )
    return sources, evidence, add


def interpretation():
    return {
        "target": "formal_requirement",
        "components": [
            {
                "id": "c1",
                "text": CLAIM,
                "claim_quote": CLAIM,
                "entities": ["orders"],
                "predicate": "require approval",
                "polarity": "positive",
                "quantities": [{"value": "42", "unit": "units", "comparator": "gt"}],
                "scope": [],
                "temporal": "currently",
                "modality": "required",
            }
        ],
        "ambiguities": [],
        "search_queries": ["orders approval requirement"],
    }


def evaluation():
    return {
        "findings": [
            {
                "component_id": "c1",
                "evidence_id": "rule",
                "source_id": "orders",
                "quotation": CLAIM,
                "relationship": "supports",
                "reason": "The passage states this requirement.",
                "scope_fit": "yes",
                "time_fit": "yes",
                "directness": "direct",
                "limitations": [],
                "basis": "direct_statement",
            }
        ],
        "unresolved_questions": [],
    }


class FakeProvider:
    def provenance(self):
        return {"provider": "mock-for-integration-test", "model": "not-a-live-model"}


class BudgetedProvider(FakeProvider):
    def provenance(self):
        return {
            **super().provenance(),
            "context_budget": {
                "input_tokens": 23552,
                "output_tokens": 8192,
                "template_reserve_tokens": 1024,
            },
        }


@pytest.fixture
def configured(tmp_path, monkeypatch):
    sources, evidence, add = frozen_corpus()
    monkeypatch.setattr(general, "read_snapshot", lambda path: (sources, evidence))
    monkeypatch.setattr(general, "get_provider", lambda: FakeProvider())
    monkeypatch.setattr(general, "interpret_claim", lambda *args: interpretation())
    monkeypatch.setattr(general, "evaluate_evidence", lambda *args: evaluation())
    monkeypatch.delenv("DECIDR_ASSESSMENT_PROVIDER", raising=False)
    monkeypatch.setenv("DECIDR_ASSESSMENT_DB", str(tmp_path / "history.sqlite"))
    previous = dict(api.app.dependency_overrides)
    api.app.dependency_overrides[api.auth.current_user] = lambda: {"id": 73}
    with TestClient(api.app) as client:
        yield client, sources, evidence, add
    api.app.dependency_overrides.clear()
    api.app.dependency_overrides.update(previous)


def test_success_is_identical_across_api_history_export_and_exact_legacy_projection(
    configured, monkeypatch
):
    client, _, evidence, _ = configured
    body = {"request_id": "canonical-success", "claim": CLAIM, "as_of": "2026-04-01"}
    response = client.post("/api/assessments/automatic", json=body)
    assert response.status_code == 201, response.text
    saved = response.json()
    snapshot = saved["snapshot"]
    result = snapshot["response"]
    canonical = result["canonical_assessment"]
    assert canonical["processing"]["status"] == "assessed"
    assert result["assessment"]["overall_outcome"] == canonical["overall_outcome"] == "Supported"
    assert result["claim_conclusion"]["label"] == canonical["overall_outcome"]
    exact = canonical["citations"][0]
    assert exact["quotation"] == CLAIM
    assert exact["start"] == evidence["rule"].text.index(CLAIM)
    projected = next(
        i for i in result["inputs"] if i["interpretation"]["citations"][0]["evidence_id"] == "rule"
    )
    assert projected["interpretation"]["citations"] == [exact]
    assert content_hash(snapshot) == saved["snapshot_sha256"]
    run_id = snapshot["run_id"]
    listing = client.get("/api/assessments").json()["items"][0]
    assert listing["overall_outcome"] == canonical["overall_outcome"]
    assert listing["confidence"]["score"] == canonical["confidence"]["score"]
    assert listing["processing"] == canonical["processing"]
    monkeypatch.setattr(
        general,
        "get_provider",
        lambda: (_ for _ in ()).throw(AssertionError("Snapshot reads must not reassess")),
    )
    assert client.get(f"/api/assessments/{run_id}/export").json() == saved
    assert client.get(f"/api/assessments/{run_id}").json() == saved
    retry = client.post("/api/assessments/automatic", json=body)
    assert retry.status_code == 200
    assert retry.json() == saved


@pytest.mark.parametrize(
    "code",
    [
        "provider_unavailable",
        "provider_failure",
        "interpretation_failure",
        "invalid_model_output",
        "unsupported_capability",
    ],
)
def test_operational_failures_save_without_assessment_outcome_or_score(
    configured, monkeypatch, code
):
    client, *_ = configured

    def fail(*args):
        raise ProviderError(code, "The configured assessment operation could not complete.")

    monkeypatch.setattr(general, "interpret_claim", fail)
    response = client.post(
        "/api/assessments/automatic",
        json={"request_id": code, "claim": CLAIM, "as_of": "2026-04-01"},
    )
    assert response.status_code == 201, response.text
    saved = response.json()
    canonical = saved["snapshot"]["response"]["canonical_assessment"]
    assert canonical["processing"]["code"] == code
    assert canonical["overall_outcome"] is None
    assert canonical["confidence"]["score"] is None
    assert isinstance(canonical["confidence"]["basis"], list)
    assert saved["snapshot"]["record_type"] == "automatic_processing_failure"
    listing = client.get("/api/assessments").json()["items"][0]
    assert listing["overall_outcome"] == "Assessment not completed"
    assert listing["processing"]["status"] == "failed"
    assert listing["confidence"]["score"] is None
    assert client.get(f"/api/assessments/{listing['run_id']}/export").json() == saved


def test_invalid_citation_fails_instead_of_fabricating_insufficient_evidence(
    configured, monkeypatch
):
    client, *_ = configured
    invalid = evaluation()
    invalid["findings"][0]["quotation"] = "A fabricated quotation."
    monkeypatch.setattr(general, "evaluate_evidence", lambda *args: invalid)
    response = client.post(
        "/api/corpus/assess-automatic", json={"claim": CLAIM, "as_of": "2026-04-01"}
    )
    canonical = response.json()["canonical_assessment"]
    assert canonical["processing"]["code"] == "invalid_model_output"
    assert canonical["overall_outcome"] is None
    assert canonical["confidence"]["score"] is None


@pytest.mark.parametrize("operation", ["snapshot_index", "retrieve_context"])
@pytest.mark.parametrize("error_type", [ValueError, OSError, sqlite3.DatabaseError])
def test_retrieval_failures_are_saved_listed_and_exported_without_a_verdict(
    configured, monkeypatch, operation, error_type
):
    client, *_ = configured

    def fail(*args, **kwargs):
        raise error_type("The retrieval data cannot be read consistently.")

    monkeypatch.setattr(general, operation, fail)
    response = client.post(
        "/api/assessments/automatic",
        json={"request_id": "retrieval-error", "claim": CLAIM, "as_of": "2026-04-01"},
    )
    assert response.status_code == 201, response.text
    saved = response.json()
    canonical = saved["snapshot"]["response"]["canonical_assessment"]
    assert canonical["processing"]["status"] == "failed"
    assert canonical["processing"]["code"] == "retrieval_failure"
    assert canonical["overall_outcome"] is None
    assert canonical["confidence"]["score"] is None
    listing = client.get("/api/assessments").json()["items"][0]
    assert listing["overall_outcome"] == "Assessment not completed"
    assert listing["processing"] == canonical["processing"]
    assert client.get(f"/api/assessments/{listing['run_id']}/export").json() == saved


def test_second_retrieval_round_failure_does_not_publish_the_first_round_as_a_verdict(
    configured, monkeypatch
):
    client, *_ = configured
    retrieve = general.retrieve_context
    calls = []

    def fail_second(*args, **kwargs):
        calls.append(kwargs)
        if len(calls) > 1:
            raise ValueError("The expansion result does not match the stored evidence.")
        return retrieve(*args, **kwargs)

    monkeypatch.setattr(general, "retrieve_context", fail_second)
    monkeypatch.setattr(
        general, "evaluate_evidence", lambda *args: {"findings": [], "unresolved_questions": []}
    )
    response = client.post(
        "/api/assessments/automatic",
        json={"request_id": "expansion-error", "claim": CLAIM, "as_of": "2026-04-01"},
    )
    assert response.status_code == 201, response.text
    result = response.json()["snapshot"]["response"]
    assert len(calls) == 2
    assert result["inputs"]  # Already-retrieved context remains inspectable, without inference.
    assert all(not item["admitted_to_framework"] for item in result["inputs"])
    assert result["canonical_assessment"]["processing"]["code"] == "retrieval_failure"
    assert result["canonical_assessment"]["overall_outcome"] is None


def test_canonical_configuration_does_not_read_the_unused_legacy_graph_config(
    configured, monkeypatch
):
    from framework import CONFIG_PATH

    client, *_ = configured
    read_text = Path.read_text

    def malformed_legacy_config(path, *args, **kwargs):
        return "{" if path == CONFIG_PATH else read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", malformed_legacy_config)
    response = client.post(
        "/api/assessments/automatic",
        json={"request_id": "canonical-config", "claim": CLAIM, "as_of": "2026-04-01"},
    )
    assert response.status_code == 201, response.text
    snapshot = response.json()["snapshot"]
    canonical = snapshot["response"]["canonical_assessment"]
    assert canonical["processing"]["status"] == "assessed"
    assert snapshot["configuration"] == {
        "assessment_method": general.METHOD,
        "canonical_schema_version": canonical["schema_version"],
        "confidence_method": canonical["confidence"]["method"],
        "confidence_weights": canonical["confidence"]["weights"],
    }


def test_successful_evaluation_with_gaps_remains_distinct_from_failure(configured, monkeypatch):
    client, *_ = configured
    calls = []

    def empty(*args):
        calls.append(args[2])
        return {
            "findings": [],
            "unresolved_questions": ["What establishes the required approver?"],
        }

    monkeypatch.setattr(general, "evaluate_evidence", empty)
    response = client.post(
        "/api/corpus/assess-automatic", json={"claim": CLAIM, "as_of": "2026-04-01"}
    )
    canonical = response.json()["canonical_assessment"]
    assert canonical["processing"]["status"] == "assessed"
    assert canonical["overall_outcome"] == "Insufficient evidence"
    assert isinstance(canonical["confidence"]["score"], int)
    assert len(canonical["diagnostics"]["retrieval_rounds"]) == 2
    assert len(calls) <= 2


def test_retrieval_expands_short_document_headers_conditions_and_explicit_links():
    sources, evidence, add = frozen_corpus()
    add(
        "linked",
        "events",
        "Order ORDER-674 followed the documented approval process.",
        kind="audit_events",
    )
    evidence["rule"].text += " Evidence example: ORDER-674."
    add(
        "unrelated",
        "onboarding",
        "New employee onboarding requires identity checks.",
        kind="procedure",
    )
    with closing(general.snapshot_index(sources, evidence)) as index:
        selected, diagnostics = general.retrieve_context(
            index, CLAIM, interpretation(), sources, evidence
        )
    ids = {p["evidence_id"] for p in selected}
    assert {"rule", "header", "conditions", "linked"} <= ids
    # Lexical retrieval can retain incidental overlap; it is not an inference edge.
    assert all("relationship" not in passage for passage in selected)
    assert diagnostics["selected_passage_count"] == len(selected)
    assert diagnostics["selection_reasons"]["header"] in {
        "same_source_context",
        "retrieved_for_claim_or_component",
    }
    assert diagnostics["selection_reasons"]["linked"] in {
        "explicit_record_reference_context",
        "retrieved_for_claim_or_component",
    }
    for passage in selected:
        assert passage["text"] == evidence[passage["evidence_id"]].text


def test_retrieval_preserves_ranked_records_and_links_before_optional_sibling_sections(
    monkeypatch,
):
    sources, evidence, add = frozen_corpus()
    add("role-seed", "roles", "Product managers manage feature requests.", heading="Product team")
    for number in range(18):
        add(
            f"role-{number}",
            "roles",
            "Other department responsibilities.",
            heading=f"Department {number}",
        )
    add(
        "interview",
        "interviews",
        "The migration was completed; see CASE-887.",
        kind="interview",
        heading="Tooling",
    )
    add(
        "interview-header",
        "interviews",
        "Interview date: 2025-06-03.",
        kind="interview",
        heading="interviews",
    )
    sources["interviews"].header_evidence = [{"quote": evidence["interview-header"].text}]
    add(
        "ranked-record",
        "tasks",
        "The old board was archived.",
        kind="task",
        row_identifier="CASE-886",
    )
    add(
        "linked-record",
        "tasks",
        "CASE-887: The replacement board is in use.",
        kind="task",
        row_identifier="CASE-887",
    )
    add(
        "unrelated-row", "tasks", "Another project's task.", kind="task", row_identifier="CASE-888"
    )
    queries = {
        CLAIM: ["role-seed", "rule"],
        "interviews": ["interview"],
        "tasks": ["ranked-record"],
    }

    def search(_connection, query, limit):
        passages = [evidence[eid] for eid in queries[query]]
        return SimpleNamespace(
            candidates=passages,
            ranked_groups=[SimpleNamespace(passages=passages)],
            additional_linked_groups=[],
        )

    monkeypatch.setattr(general, "search_corpus", search)
    monkeypatch.setattr(general, "MAX_PASSAGES", 9)
    selected, diagnostics = general.retrieve_context(
        None, CLAIM, {"search_queries": ["interviews", "tasks"]}, sources, evidence
    )
    ids = {p["evidence_id"] for p in selected}
    assert {
        "rule",
        "header",
        "conditions",
        "role-seed",
        "interview",
        "interview-header",
        "ranked-record",
        "linked-record",
    } <= ids
    assert "unrelated-row" not in ids
    assert len(ids & {f"role-{number}" for number in range(18)}) <= 1
    assert diagnostics["omitted_passage_count"] > 0
    assert diagnostics["selection_reasons"]["linked-record"] == "explicit_record_reference_context"
    assert all(p["text"] == evidence[p["evidence_id"]].text for p in selected)


def test_retrieval_balances_ranked_sources_and_does_not_follow_unselected_sibling_references(
    monkeypatch,
):
    sources, evidence, add = frozen_corpus()
    for number in range(8):
        add(
            f"section-{number}",
            "handbook",
            "A retrieved handbook section.",
            heading=f"Topic {number}",
        )
    add(
        "unrelated-sibling",
        "handbook",
        "For an unrelated process see CASE-899.",
        heading="Other process",
    )
    add(
        "unrelated-link",
        "events",
        "CASE-899 was completed.",
        kind="task",
        row_identifier="CASE-899",
    )
    results = SimpleNamespace(
        candidates=list(evidence.values()),
        ranked_groups=[
            SimpleNamespace(passages=[evidence[f"section-{n}"] for n in range(8)]),
            SimpleNamespace(passages=[evidence["rule"]]),
        ],
        additional_linked_groups=[],
    )
    monkeypatch.setattr(general, "search_corpus", lambda *_args, **_kwargs: results)
    monkeypatch.setattr(general, "MAX_PASSAGES", 6)
    selected, diagnostics = general.retrieve_context(None, CLAIM, {}, sources, evidence)
    ids = [p["evidence_id"] for p in selected]
    assert {"rule", "header", "conditions"} <= set(ids)
    assert ids.index("rule") < ids.index("section-1")
    assert "unrelated-link" not in diagnostics["selection_reasons"]


def test_ranked_section_lead_precedes_earlier_unrelated_paragraphs_and_keeps_adjacent_caveat(
    monkeypatch,
):
    sources, evidence, add = frozen_corpus()
    for number in range(1, 6):
        add(
            f"interview-{number}",
            "interviews",
            f"Interview paragraph {number}.",
            kind="interview",
            heading="Discussion",
            paragraph=number,
        )
    group = SimpleNamespace(
        lead_result=SimpleNamespace(evidence_id="interview-4"),
        passages=[evidence[f"interview-{n}"] for n in range(1, 6)],
    )
    result = SimpleNamespace(
        candidates=group.passages, ranked_groups=[group], additional_linked_groups=[]
    )
    monkeypatch.setattr(general, "search_corpus", lambda *_a, **_kw: result)
    monkeypatch.setattr(general, "MAX_PASSAGES", 5)
    selected, _ = general.retrieve_context(None, CLAIM, {}, sources, evidence)
    assert [p["evidence_id"] for p in selected] == [
        "interview-4",
        "interview-1",
        "interview-2",
        "interview-3",
        "interview-5",
    ]


def test_retrieval_searches_material_components_and_bounds_gap_expansion(monkeypatch):
    sources, evidence, add = frozen_corpus()
    add(
        "dispatch",
        "warehouse",
        "Warehouse dispatches are scanned before loading.",
        kind="audit_events",
    )
    calls = []

    def search(_connection, query, limit):
        calls.append((query, limit))
        passages = (
            [evidence["dispatch"]] if query == "Dispatches are scanned before loading." else []
        )
        return SimpleNamespace(
            candidates=passages,
            ranked_groups=[SimpleNamespace(passages=passages)] if passages else [],
            additional_linked_groups=[],
        )

    monkeypatch.setattr(general, "search_corpus", search)
    parsed = {
        "components": [{"text": "Dispatches are scanned before loading."}],
        "search_queries": [],
    }
    selected, diagnostics = general.retrieve_context(
        None, "The workflow is followed.", parsed, sources, evidence
    )
    assert "dispatch" in {p["evidence_id"] for p in selected}
    assert all(limit == 8 for _, limit in calls)
    assert diagnostics["ranked_group_limit"] == 8
    calls.clear()
    general.retrieve_context(
        None,
        "The workflow is followed.",
        parsed,
        sources,
        evidence,
        questions=["Which dispatches bypassed scanning?"],
        exclude={"dispatch"},
    )
    assert calls[1][0] == "Which dispatches bypassed scanning?"
    assert all(limit == 12 for _, limit in calls)


@pytest.mark.parametrize("reference_in_header", [False, True])
def test_document_reference_selects_actual_document_before_unrelated_mentions(
    monkeypatch, reference_in_header
):
    sources, evidence, add = frozen_corpus()
    add("reference", "shipping", "Loading follows GUIDE-731.", kind="interview", heading="Loading")
    if reference_in_header:
        sources["shipping"].header_evidence = [{"quote": evidence["reference"].text}]
    add(
        "requirement",
        "archive:GUIDE-731",
        "Sealed loads require a second inspection.",
        heading="Requirements",
    )
    add("scope", "archive:GUIDE-731", "Applies to refrigerated loads only.", heading="Scope")
    add(
        "metadata",
        "archive:GUIDE-731",
        "Effective date: 2025-03-01.",
        heading="GUIDE-731 — Loading Manual",
    )
    sources["archive:GUIDE-731"].title = "GUIDE-731 — Loading Manual"
    sources["archive:GUIDE-731"].header_evidence = [{"quote": evidence["metadata"].text}]
    for n in range(12):
        add(f"mention-{n}", f"other-{n}", "A different team's notes mention GUIDE-731.")
    result = SimpleNamespace(
        candidates=[evidence["reference"], evidence["requirement"]],
        ranked_groups=[SimpleNamespace(passages=[evidence["reference"]])],
        additional_linked_groups=[],
    )
    monkeypatch.setattr(general, "search_corpus", lambda *_a, **_kw: result)
    monkeypatch.setattr(general, "MAX_PASSAGES", 4)
    selected, diagnostics = general.retrieve_context(
        None, "Inspect sealed loads.", {}, sources, evidence
    )
    ids = [p["evidence_id"] for p in selected]
    assert {"requirement", "scope"} <= set(ids)
    assert not any(eid.startswith("mention-") for eid in ids)
    assert diagnostics["selection_reasons"]["requirement"] == "explicit_document_reference_context"
    assert all(p["text"] == evidence[p["evidence_id"]].text for p in selected)
    assert next(p for p in selected if p["evidence_id"] == "requirement")["source"] == sources[
        "archive:GUIDE-731"
    ].model_dump(mode="json")


def test_mixed_header_and_policy_body_remains_substantive_priority(monkeypatch):
    sources, evidence, add = frozen_corpus()
    text = (
        "# Inspection Manual\nOwner: Quality Team\n"
        "When a seal is broken, the shipment requires a second inspection before dispatch."
    )
    add("mixed-rule", "inspection", text, heading="Inspection Manual")
    sources["inspection"].title = "Inspection Manual"
    sources["inspection"].header_evidence = [{"quote": "Owner: Quality Team"}]
    add("background", "logistics", "Dispatch volume increased last week.")
    result = SimpleNamespace(
        candidates=[evidence[eid] for eid in ("mixed-rule", "background")],
        ranked_groups=[
            SimpleNamespace(passages=[evidence[eid]]) for eid in ("mixed-rule", "background")
        ],
        additional_linked_groups=[],
    )
    monkeypatch.setattr(general, "search_corpus", lambda *_a, **_kw: result)
    monkeypatch.setattr(general, "MAX_PASSAGES", 1)
    selected, _ = general.retrieve_context(
        None, "Broken seals require inspection.", {}, sources, evidence
    )
    assert [p["evidence_id"] for p in selected] == ["mixed-rule"]
    assert selected[0]["text"] == evidence["mixed-rule"].text == text
    assert selected[0]["source"] == sources["inspection"].model_dump(mode="json")


def test_metadata_headers_do_not_displace_substantive_root_level_table(monkeypatch):
    sources, evidence, add = frozen_corpus()
    add(
        "table",
        "routing",
        "| Region | Actual route |\n| North | Direct dispatch |",
        heading="Routing Table",
    )
    sources["routing"].title = "Routing Table"
    add("dated-header", "routing", "Updated: 2026-02-03.", heading="Routing Table")
    sources["routing"].header_evidence = [{"quote": evidence["dated-header"].text}]
    add(
        "dispatch",
        "warehouse",
        "North dispatch completed without the intermediate depot.",
        kind="audit_events",
    )
    result = SimpleNamespace(
        candidates=[evidence[eid] for eid in ("dated-header", "table", "dispatch")],
        ranked_groups=[
            SimpleNamespace(passages=[evidence[eid]])
            for eid in ("dated-header", "table", "dispatch")
        ],
        additional_linked_groups=[],
    )
    monkeypatch.setattr(general, "search_corpus", lambda *_a, **_kw: result)
    monkeypatch.setattr(general, "MAX_PASSAGES", 2)
    selected, _ = general.retrieve_context(
        None, "North dispatch uses the depot.", {}, sources, evidence
    )
    assert {p["evidence_id"] for p in selected} == {"table", "dispatch"}
    assert (
        next(p for p in selected if p["evidence_id"] == "table")["source"]["header_evidence"]
        == sources["routing"].header_evidence
    )


@pytest.mark.parametrize("target", ["observed_practice", "current_state"])
def test_operational_targets_prioritise_observed_sources_over_policy_context(monkeypatch, target):
    sources, evidence, add = frozen_corpus()
    add("event", "dispatch", "A sealed shipment bypassed the depot.", kind="audit_events")
    result = SimpleNamespace(
        candidates=[evidence["rule"], evidence["event"]],
        ranked_groups=[SimpleNamespace(passages=[evidence[eid]]) for eid in ("rule", "event")],
        additional_linked_groups=[],
    )
    monkeypatch.setattr(general, "search_corpus", lambda *_a, **_kw: result)
    monkeypatch.setattr(general, "MAX_PASSAGES", 1)
    selected, _ = general.retrieve_context(
        None, "Shipments use the depot.", {"target": target}, sources, evidence
    )
    assert [p["evidence_id"] for p in selected] == ["event"]


@pytest.mark.parametrize("exclusion", ["policy_for_practice", "different_scope", "draft_rule"])
def test_unadmitted_model_support_cannot_suppress_gap_retrieval(
    configured, monkeypatch, exclusion
):
    _, sources, evidence, add = configured
    parsed = interpretation()
    if exclusion == "policy_for_practice":
        parsed["target"] = "observed_practice"
    elif exclusion == "draft_rule":
        sources["orders"].lifecycle_status = "draft"
    actual_text = (
        "Orders above 42 units received manager approval."
        if exclusion == "policy_for_practice"
        else CLAIM
    )
    add(
        "actual",
        "operations",
        actual_text,
        kind="interview" if exclusion == "policy_for_practice" else "policy",
    )
    monkeypatch.setattr(general, "interpret_claim", lambda *_a: parsed)
    retrievals, evaluations = [], []

    def retrieve(*_args, **kwargs):
        retrievals.append(kwargs)
        eid = "actual" if kwargs.get("exclude") else "rule"
        p = evidence[eid]
        return [
            {"evidence_id": eid, "source_id": p.source_id, "text": p.text, "locator": p.locator}
        ], {}

    def evaluate(_interpretation, _claim, selected, *_args):
        evaluations.append([p["evidence_id"] for p in selected])
        result = evaluation()
        if exclusion == "different_scope":
            result["findings"][0]["scope_fit"] = "no"
        if len(selected) > 1:
            result["findings"].append(
                {
                    **evaluation()["findings"][0],
                    "evidence_id": "actual",
                    "source_id": "operations",
                    "quotation": actual_text,
                    "basis": "reported_statement"
                    if exclusion == "policy_for_practice"
                    else "direct_statement",
                }
            )
        return result

    monkeypatch.setattr(general, "retrieve_context", retrieve)
    monkeypatch.setattr(general, "evaluate_evidence", evaluate)
    request = InterpretationProposalRequest(claim=CLAIM, as_of=date(2026, 4, 1))
    bundle = general.build_general_bundle(request, Path("/unused.sqlite"))
    assert evaluations == [["rule"], ["rule", "actual"]]
    assert retrievals[1]["questions"] == [CLAIM]
    findings = bundle["response"]["canonical_assessment"]["components"][0]["findings"]
    assert not next(f for f in findings if f["evidence_id"] == "rule")["admitted"]
    assert next(f for f in findings if f["evidence_id"] == "actual")["admitted"]


def test_target_conflict_is_processing_failure_without_rewriting_claim(configured):
    client, *_ = configured
    response = client.post(
        "/api/corpus/assess-automatic",
        json={"claim": CLAIM, "as_of": "2026-04-01", "assessment_target": "underlying_event"},
    )
    result = response.json()
    assert result["claim_text"] == CLAIM
    assert result["canonical_assessment"]["processing"]["status"] == "failed"
    assert result["canonical_assessment"]["overall_outcome"] is None


def test_second_retrieval_round_shares_total_character_budget(configured, monkeypatch):
    monkeypatch.setattr(general, "MAX_CHARACTERS", 100)
    first = {"evidence_id": "rule", "source_id": "orders", "locator": "rule", "text": "x" * 60}
    second = {
        "evidence_id": "header",
        "source_id": "orders",
        "locator": "header",
        "text": "y" * 60,
    }
    calls = []

    def retrieve(*args, **kwargs):
        selected = [second] if kwargs.get("exclude") else [first]
        return deepcopy(selected), {"selected_passage_count": 1, "omitted_passage_count": 0}

    def evaluate(*args):
        calls.append(args[2])
        assert sum(len(p["text"]) for p in args[2]) <= 100
        return {"findings": [], "unresolved_questions": []}

    monkeypatch.setattr(general, "retrieve_context", retrieve)
    monkeypatch.setattr(general, "evaluate_evidence", evaluate)
    request = InterpretationProposalRequest(claim=CLAIM, as_of=date(2026, 4, 1))
    result = general.build_general_bundle(request, Path("/unused.sqlite"))
    assert result["response"]["canonical_assessment"]["processing"]["status"] == "assessed"
    assert len(calls) == 1


def test_model_budget_omits_whole_metadata_heavy_passage_and_saves_exact_remaining_evidence(
    configured, monkeypatch
):
    client, sources, evidence, add = configured
    add("large-metadata", "large", "A short but unrelated note.")
    sources["large"].metadata_notes = "Source provenance detail. " * 5000
    passages = [
        {
            "evidence_id": eid,
            "source_id": evidence[eid].source_id,
            "locator": evidence[eid].locator,
            "text": evidence[eid].text,
            "heading": evidence[eid].heading,
            "source": sources[evidence[eid].source_id].model_dump(mode="json"),
        }
        for eid in ["rule", "header", "conditions", "large-metadata"]
    ]
    before = deepcopy(passages)
    monkeypatch.setattr(general, "get_provider", BudgetedProvider)
    monkeypatch.setattr(
        general,
        "retrieve_context",
        lambda *_a, **_kw: (passages, {"selected_passage_count": len(passages)}),
    )
    evaluated = []

    def evaluate(_interpretation, _claim, selected, *_args):
        evaluated.append(deepcopy(selected))
        return evaluation()

    monkeypatch.setattr(general, "evaluate_evidence", evaluate)
    response = client.post(
        "/api/assessments/automatic",
        json={"request_id": "model-budget", "claim": CLAIM, "as_of": "2026-04-01"},
    )
    assert response.status_code == 201
    saved = response.json()
    canonical = saved["snapshot"]["response"]["canonical_assessment"]
    assert canonical["overall_outcome"] == "Supported"
    budget = canonical["diagnostics"]["retrieval_rounds"][0]["model_input_budget"]
    assert budget["fits"] is True
    assert budget["omitted_evidence_ids"] == ["large-metadata"]
    assert budget["selected_passage_count"] == 3
    assert evaluated == [before[:3]]
    assert passages == before
    assert any(
        s["source_id"] == "large" and s["metadata_notes"] == sources["large"].metadata_notes
        for s in saved["snapshot"]["sources"]
    )
    assert client.get(f"/api/assessments/{saved['snapshot']['run_id']}/export").json() == saved


def test_no_complete_passage_fits_model_budget_is_saved_processing_failure(
    configured, monkeypatch
):
    client, sources, evidence, _ = configured
    sources["orders"].metadata_notes = "Unabridged provenance. " * 5000
    monkeypatch.setattr(general, "get_provider", BudgetedProvider)
    monkeypatch.setattr(
        general,
        "evaluate_evidence",
        lambda *_args: pytest.fail("Over-budget evidence must not reach the model"),
    )
    response = client.post(
        "/api/assessments/automatic",
        json={"request_id": "no-budget", "claim": CLAIM, "as_of": "2026-04-01"},
    )
    saved = response.json()
    canonical = saved["snapshot"]["response"]["canonical_assessment"]
    assert canonical["processing"]["code"] == "unsupported_capability"
    assert canonical["overall_outcome"] is None
    assert canonical["confidence"]["score"] is None
    budget = canonical["diagnostics"]["retrieval_rounds"][0]["model_input_budget"]
    assert set(budget["omitted_evidence_ids"]) == set(evidence)
    assert budget["selected_passage_count"] == 0
    assert client.get(f"/api/assessments/{saved['snapshot']['run_id']}/export").json() == saved


def test_second_round_model_budget_accounts_for_retained_first_round_evidence(
    configured, monkeypatch
):
    _, sources, evidence, _ = configured
    passages = [
        {
            "evidence_id": eid,
            "source_id": "orders",
            "locator": evidence[eid].locator,
            "text": evidence[eid].text,
            "source": sources["orders"].model_dump(mode="json"),
        }
        for eid in ["rule", "header", "conditions"]
    ]
    monkeypatch.setattr(
        general,
        "retrieve_context",
        lambda *_a, **kw: (passages[1:] if kw.get("exclude") else passages[:1], {}),
    )
    checks = []

    def budget(_interpretation, _claim, selected, *_args):
        ids = [p["evidence_id"] for p in selected]
        checks.append(ids)
        return {
            "fits": len(ids) <= 2,
            "input_limit_tokens": 2,
            "generation_input_tokens": len(ids),
        }

    monkeypatch.setattr(general, "evidence_input_budget", budget)
    evaluated = []

    def evaluate(_interpretation, _claim, selected, *_args):
        evaluated.append([p["evidence_id"] for p in selected])
        return {"findings": [], "unresolved_questions": []}

    monkeypatch.setattr(general, "evaluate_evidence", evaluate)
    request = InterpretationProposalRequest(claim=CLAIM, as_of=date(2026, 4, 1))
    bundle = general.build_general_bundle(request, Path("/unused.sqlite"))
    assert evaluated == [["rule"], ["rule", "header"]]
    assert ["rule", "header", "conditions"] in checks
    round_two = bundle["response"]["canonical_assessment"]["diagnostics"]["retrieval_rounds"][1]
    assert round_two["added_passage_count"] == 1
    assert round_two["model_input_budget"]["omitted_evidence_ids"] == ["conditions"]


def test_frozen_inputs_and_models_provenance_are_preserved(configured):
    _, sources, evidence, _ = configured
    before = (
        {key: s.model_dump() for key, s in sources.items()},
        {key: e.model_dump() for key, e in evidence.items()},
    )
    request = InterpretationProposalRequest(claim=CLAIM, as_of=date(2026, 4, 1))
    bundle = general.build_general_bundle(request, Path("/unused.sqlite"))
    assert bundle["provenance"]["provider"]["model"] == "not-a-live-model"
    assert bundle["provenance"]["corpus_index_sha256"]
    assert before == (
        {key: s.model_dump() for key, s in sources.items()},
        {key: e.model_dump() for key, e in evidence.items()},
    )


def test_canonical_review_reassesses_frozen_parent_and_preserves_history(configured, monkeypatch):
    client, _, evidence, _ = configured
    parent = client.post(
        "/api/assessments/automatic",
        json={"request_id": "parent-review", "claim": CLAIM, "as_of": "2026-04-01"},
    ).json()
    run_id = parent["snapshot"]["run_id"]
    before_hash = parent["snapshot_sha256"]
    evidence["rule"].text = "The live corpus has changed after the saved result."

    def forbidden(*args):
        raise AssertionError("Human review must not call a provider or read the current corpus")

    monkeypatch.setattr(general, "get_provider", forbidden)
    monkeypatch.setattr(general, "read_snapshot", forbidden)
    findings = evaluation()["findings"]
    findings[0].update(
        relationship="qualifies",
        scope_fit="unknown",
        reason="The passage does not establish the submitted scope.",
    )
    body = {
        "request_id": "review-one",
        "revision_reason": "The stated scope requires review.",
        "findings": findings,
    }
    response = client.post(f"/api/assessments/{run_id}/review-canonical", json=body)
    assert response.status_code == 201, response.text
    saved = response.json()
    snapshot = saved["snapshot"]
    result = snapshot["response"]
    assert snapshot["parent_run_id"] == run_id
    assert snapshot["parent_snapshot_sha256"] == before_hash
    assert snapshot["record_type"] == "canonical_human_review"
    assert snapshot["provenance"]["revision_basis"] == "frozen_parent_snapshot"
    assert snapshot["provenance"]["review_basis"] == "human_supplied_judgements"
    assert result["status"] == "assessed_supplied_judgements"
    assert result["assessment"]["overall_outcome"] == "Insufficient evidence"
    canonical = result["canonical_assessment"]
    assert canonical["overall_outcome"] == result["assessment"]["overall_outcome"]
    assert (
        canonical["citations"]
        == parent["snapshot"]["response"]["canonical_assessment"]["citations"]
    )
    assert "semantic_validation" not in canonical["components"][0]["findings"][0]
    assert result["assurance"]["human_review"] == "declared_by_user"
    assert content_hash(snapshot) == saved["snapshot_sha256"]
    assert client.get(f"/api/assessments/{run_id}").json() == parent
    assert client.get(f"/api/assessments/{snapshot['run_id']}/export").json() == saved
    retry = client.post(f"/api/assessments/{run_id}/review-canonical", json=body)
    assert retry.status_code == 200 and retry.json() == saved


@pytest.mark.parametrize(
    "mutation", ["quotation", "source", "component", "duplicate", "drop", "model_validation"]
)
def test_canonical_review_rejects_changed_bindings_or_forged_model_validation(
    configured, mutation
):
    client, *_ = configured
    parent = client.post(
        "/api/assessments/automatic",
        json={"request_id": "binding-parent", "claim": CLAIM, "as_of": "2026-04-01"},
    ).json()
    run_id = parent["snapshot"]["run_id"]
    findings = evaluation()["findings"]
    if mutation == "quotation":
        findings[0]["quotation"] = "A different quotation cannot replace the saved citation."
    elif mutation == "source":
        findings[0]["source_id"] = "other"
    elif mutation == "component":
        findings[0]["component_id"] = "other-component"
    elif mutation == "duplicate":
        findings.append(deepcopy(findings[0]))
    elif mutation == "drop":
        findings.clear()
    else:
        findings[0]["semantic_validation"] = {"valid": True, "reason": "Claimed model validation"}
    response = client.post(
        f"/api/assessments/{run_id}/review-canonical",
        json={
            "request_id": "bad-review",
            "revision_reason": "Check this finding.",
            "findings": findings,
        },
    )
    assert response.status_code == 422, response.text
    assert client.get(f"/api/assessments/{run_id}").json() == parent
    assert len(client.get("/api/assessments").json()["items"]) == 1


def test_canonical_review_is_owner_scoped_and_old_review_route_is_blocked(configured):
    client, *_ = configured
    parent = client.post(
        "/api/assessments/automatic",
        json={"request_id": "owner-parent", "claim": CLAIM, "as_of": "2026-04-01"},
    ).json()
    run_id = parent["snapshot"]["run_id"]
    legacy = deepcopy(parent["snapshot"]["request"])
    for item in legacy["inputs"]:
        item.update(directness=0.0, specificity=0.0, completeness=0.0)
    old = client.post(
        "/api/assessments",
        json={
            "request_id": "legacy-revision",
            "parent_run_id": run_id,
            "revision_reason": "Should use canonical route.",
            "assessment": legacy,
        },
    )
    assert old.status_code == 409, old.text
    api.app.dependency_overrides[api.auth.current_user] = lambda: {"id": 91}
    response = client.post(
        f"/api/assessments/{run_id}/review-canonical",
        json={
            "request_id": "other-owner",
            "revision_reason": "Check the result.",
            "findings": evaluation()["findings"],
        },
    )
    assert response.status_code == 404


def context_payload(eid, sid, text):
    return {"evidence_id": eid, "source_id": sid, "locator": eid, "text": text}


def test_context_supersedes_orientation_preserves_other_pairing_and_exact_citations():
    sources, _, add = frozen_corpus()
    add("old", "old-policy", "POL-803 requires written approval.")
    add("new", "new-policy", "POL-804 supersedes POL-803.")
    add("note", "note-source", "POL-803 was discussed in the meeting.", kind="meeting")
    sources["new-policy"].predecessor_source_id = "old-policy"
    selected = [
        context_payload("old", "old-policy", "POL-803 requires written approval."),
        context_payload("new", "new-policy", "POL-804 supersedes POL-803."),
        context_payload("note", "note-source", "POL-803 was discussed in the meeting."),
    ]
    result = general.context_connections(selected, sources)
    supersedes = next(edge for edge in result if edge["relationship"] == "supersedes")
    assert supersedes["from_citation"]["evidence_id"] == "new"
    assert supersedes["to_citation"]["evidence_id"] == "old"
    assert any(
        edge["from_citation"]["evidence_id"] == "old"
        and edge["to_citation"]["evidence_id"] == "note"
        for edge in result
    )
    reversed_pair = general.context_connections([selected[1], selected[0]], sources)[0]
    assert reversed_pair["relationship"] == "supersedes"
    assert reversed_pair["from_citation"]["evidence_id"] == "new"
    texts = {p["evidence_id"]: p["text"] for p in selected}
    for edge in result:
        assert edge["inferential"] is False
        for key in ("from_citation", "to_citation"):
            citation = edge[key]
            assert (
                texts[citation["evidence_id"]][citation["start"] : citation["end"]]
                == citation["quotation"]
            )


def test_context_record_identity_requires_both_rows_to_identify_the_same_record():
    sources, _, add = frozen_corpus()
    add("one", "ledger-one", "Placeholder", kind="crm_records")
    add("two", "ledger-two", "Placeholder", kind="audit_events")
    first = context_payload(
        "one",
        "ledger-one",
        json.dumps({"record_id": "CASE-401", "notes": "Compared with CASE-402"}),
    )
    other = context_payload(
        "two",
        "ledger-two",
        json.dumps({"record_id": "CASE-402", "notes": "Compared with CASE-401"}),
    )
    assert (
        general.context_connections([first, other], sources)[0]["relationship"]
        == "contextual_reference"
    )
    linked = context_payload(
        "two", "ledger-two", json.dumps({"record_id": "AUD-998", "related_record": "CASE-401"})
    )
    assert (
        general.context_connections([first, linked], sources)[0]["relationship"] == "same_record"
    )
    unrelated = context_payload("two", "ledger-two", json.dumps({"record_id": "CASE-4010"}))
    assert general.context_connections([first, unrelated], sources) == []


def test_context_graph_paths_and_cycles_cannot_change_assessment_confidence(configured):
    _, sources, _, add = configured
    add("copy-a", "copy-source-a", "CASE-609 is retained as context.", kind="meeting")
    add("copy-b", "copy-source-b", "CASE-609 is retained as context.", kind="meeting")
    sources["copy-source-a"].derived_from_source_id = "copy-source-b"
    sources["copy-source-b"].derived_from_source_id = "copy-source-a"
    request = InterpretationProposalRequest(claim=CLAIM, as_of=date(2026, 4, 1))
    bundle = general.build_general_bundle(request, Path("/unused.sqlite"))
    canonical = bundle["response"]["canonical_assessment"]
    confidence = deepcopy(canonical["confidence"])
    outcome = canonical["overall_outcome"]
    selected = [
        context_payload("copy-a", "copy-source-a", "CASE-609 is retained as context."),
        context_payload("copy-b", "copy-source-b", "CASE-609 is retained as context."),
    ]
    for _ in range(3):
        general.project_response(request, canonical, selected + selected, sources)
    assert canonical["context_relations"]
    assert all(edge["inferential"] is False for edge in canonical["context_relations"])
    assert canonical["confidence"] == confidence
    assert canonical["overall_outcome"] == outcome


@pytest.mark.parametrize(
    "wording",
    [
        "POL-804 does not supersede POL-803.",
        "POL-804 is not superseded by POL-803.",
        "If adopted, POL-804 supersedes POL-803.",
        "Draft: POL-804 supersedes POL-803.",
    ],
)
def test_supersession_requires_affirmative_adoption_wording(wording):
    sources, _, add = frozen_corpus()
    add("old", "old-policy", "POL-803 requirements.")
    add("new", "new-policy", wording)
    sources["new-policy"].predecessor_source_id = "old-policy"
    selected = [
        context_payload("old", "old-policy", "POL-803 requirements."),
        context_payload("new", "new-policy", wording),
    ]
    edge = general.context_connections(selected, sources)[0]
    assert edge["relationship"] == "contextual_reference"
    assert edge["inferential"] is False


def test_unchanged_review_preserves_derived_temporal_headers_and_confidence(
    configured, monkeypatch
):
    from decidr.claim_interpreter import Finding

    client, sources, evidence, _ = configured
    source = sources["orders"]
    source.approval_status = "Approved"
    source.effective_start_date = date(2025, 2, 3)
    source.metadata_provenance = {
        "approval_status": "direct:markdown_metadata:approval status",
        "effective_date": "direct:markdown_metadata:effective date",
    }
    source.header_evidence = [
        {
            "key": "approval status",
            "value": "Approved",
            "quote": "- **Approval status:** Approved",
            "scope": "document_header",
            "source_id": "orders",
        },
        {
            "key": "effective date",
            "value": "2025-02-03",
            "quote": "- **Effective date:** 2025-02-03",
            "scope": "document_header",
            "source_id": "orders",
        },
    ]
    evidence["header"].text = "\n".join(header["quote"] for header in source.header_evidence)
    output = evaluation()
    output["findings"][0]["time_fit"] = "unknown"
    monkeypatch.setattr(general, "evaluate_evidence", lambda *args: deepcopy(output))
    response = client.post(
        "/api/assessments/automatic",
        json={"request_id": "dated-parent", "claim": CLAIM, "as_of": "2026-04-01"},
    )
    assert response.status_code == 201, response.text
    parent = response.json()
    canonical = parent["snapshot"]["response"]["canonical_assessment"]
    assert canonical["overall_outcome"] == "Supported"
    assert len(canonical["citations"]) == 3
    finding = canonical["components"][0]["findings"][0]
    assert finding["original_time_fit"] == "unknown"
    review = client.post(
        f"/api/assessments/{parent['snapshot']['run_id']}/review-canonical",
        json={
            "request_id": "dated-review",
            "revision_reason": "Reviewed the unchanged requirement and exact effective-date headers.",
            "findings": [
                {key: value for key, value in finding.items() if key in Finding.model_fields}
            ],
        },
    )
    assert review.status_code == 201, review.text
    revised = review.json()["snapshot"]["response"]["canonical_assessment"]
    assert revised["citations"] == canonical["citations"]
    assert revised["confidence"] == canonical["confidence"]
    assert (
        revised["components"][0]["findings"][0]["temporal_derivation"]
        == finding["temporal_derivation"]
    )
    assert client.get(f"/api/assessments/{parent['snapshot']['run_id']}").json() == parent


def test_canonical_review_cannot_readmit_exclusive_trigger_as_inclusive_support(
    configured, monkeypatch
):
    from decidr.claim_interpreter import Finding

    client, _, evidence, add = configured
    claim = "Discounts of 27% or more require Compliance approval."
    narrower = "Compliance has approval authority above 27%."
    evidence["rule"].text = claim
    add("exclusive-role", "roles", narrower, kind="organisational_information")
    interpreted = interpretation()
    interpreted["components"][0].update(
        text=claim,
        claim_quote=claim,
        entities=["Compliance"],
        predicate="require approval",
        quantities=[{"value": "27", "unit": "%", "comparator": "gte"}],
    )
    interpreted["search_queries"] = ["discount Compliance approval"]
    evaluated = evaluation()
    evaluated["findings"][0].update(quotation=claim)
    evaluated["findings"].append(
        {
            **evaluated["findings"][0],
            "evidence_id": "exclusive-role",
            "source_id": "roles",
            "quotation": narrower,
        }
    )
    monkeypatch.setattr(general, "interpret_claim", lambda *args: deepcopy(interpreted))
    monkeypatch.setattr(general, "evaluate_evidence", lambda *args: deepcopy(evaluated))
    response = client.post(
        "/api/assessments/automatic",
        json={"request_id": "boundary-parent", "claim": claim, "as_of": "2026-04-01"},
    )
    assert response.status_code == 201, response.text
    parent = response.json()
    original = parent["snapshot"]["response"]["canonical_assessment"]
    assert original["overall_outcome"] == "Supported"
    findings = [
        {key: value for key, value in f.items() if key in Finding.model_fields}
        for c in original["components"]
        for f in c["findings"]
    ]
    excluded = next(f for f in findings if f["evidence_id"] == "exclusive-role")
    assert excluded["relationship"] == "context"
    excluded.update(
        relationship="supports",
        scope_fit="yes",
        time_fit="yes",
        reason="The reviewer attempts to admit the exclusive threshold as inclusive support.",
    )
    review = client.post(
        f"/api/assessments/{parent['snapshot']['run_id']}/review-canonical",
        json={
            "request_id": "boundary-review",
            "revision_reason": "Check the boundary interpretation.",
            "findings": findings,
        },
    )
    assert review.status_code == 201, review.text
    revised = review.json()["snapshot"]["response"]["canonical_assessment"]
    role = next(
        f
        for c in revised["components"]
        for f in c["findings"]
        if f["evidence_id"] == "exclusive-role"
    )
    assert role["relationship"] == "context" and not role["admitted"]
    assert role["exclusion_reasons"]
    assert revised["confidence"] == original["confidence"]
    assert revised["citations"] == original["citations"]
    assert client.get(f"/api/assessments/{parent['snapshot']['run_id']}").json() == parent
