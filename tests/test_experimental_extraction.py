"""Experimental contract and reasoning checks; no human-labelled accuracy claim."""

from copy import deepcopy

from decidr.experimental_extraction import (
    Statement,
    assertion_graph,
    boundary_relation,
    compare_extraction,
    compare_statement,
    temporal_status,
    units_for,
    validate_extraction,
)


def frame(**values):
    fields = {
        name: ([] if name in {"conditions", "exceptions"} else {"value": None, "citations": []})
        for name in Statement.model_fields
    }
    for name, value in values.items():
        fields[name] = (
            [{"value": v, "citations": []} for v in value]
            if isinstance(value, list)
            else {"value": value, "citations": []}
        )
    return fields


def record():
    return {
        "evidence_id": "E-development",
        "source_id": "S-development",
        "locator": "Rules",
        "text": "The Facilities Lead approves roof inspections. Authority is not formally assigned.",
        "source": {
            "source_type": "policy",
            "lifecycle_status": "current",
            "title": "Inspection policy",
            "effective_start_date": "2025-01-01",
            "effective_end_date": "2025-12-31",
            "creation_date": "2024-12-01",
        },
    }


def test_span_origin_unknowns_and_valid_quote_do_not_certify_meaning():
    units = units_for("A role has formal authority.", "prescribed_rule", record())
    claim = frame(authority_status="assigned")
    claim["authority_status"]["citations"] = [
        {"unit": "PASSAGE", "quote": "Authority is not formally assigned."}
    ]
    source = frame(
        authority_status="assigned"
    )  # Deliberately wrong meaning with a real quotation.
    source["authority_status"]["citations"] = [
        {"unit": "PASSAGE", "quote": "Authority is not formally assigned."}
    ]
    checked = validate_extraction({"claim": claim, "assertions": [source]}, units)
    assert checked["extraction"]["claim"]["authority_status"]["value"] is None
    assert checked["validation_errors"][0]["component"] == "claim.authority_status"
    assert checked["extraction"]["assertions"][0]["authority_status"]["value"] == "assigned"
    assert checked["established_facts"] == []
    assert checked["semantic_validation"] == "not_independently_adjudicated"
    assert compare_extraction(checked)["relationship"] is None
    source["authority_status"]["citations"][0]["quote"] = "An invented quotation"
    checked = validate_extraction({"claim": frame(), "assertions": [source]}, units)
    assert checked["extraction"]["assertions"][0]["authority_status"]["value"] is None


def test_authority_negation_target_scope_and_events_are_separate():
    base = frame(
        actor="Facilities Lead",
        action="approve",
        object="roof_inspection",
        authority_status="assigned",
        target="prescribed_rule",
        negation="positive",
    )
    source = deepcopy(base)
    source["authority_status"]["value"] = "unassigned"
    assert compare_statement(base, source)["relationship"] == "contradict"
    source["authority_status"]["value"] = "not_documented"
    assert compare_statement(base, source)["relationship"] == "qualify"
    source = deepcopy(base)
    source["target"]["value"] = "actual_practice"
    assert compare_statement(base, source)["relationship"] == "contextual"
    source = deepcopy(base)
    base["start_event"]["value"] = "assignment"
    source["start_event"]["value"] = "contract_signature"
    assert compare_statement(base, source)["relationship"] == "qualify"
    source["start_event"]["value"] = None
    assert compare_statement(base, source)["relationship"] is None


def test_boundaries_preserve_units_and_inclusivity():
    assert (
        boundary_relation("eq:500:currency:expense", "gte:500:currency:expense", "amount")
        == "support"
    )
    assert (
        boundary_relation("eq:500:currency:expense", "gt:500:currency:expense", "amount")
        == "qualify"
    )
    assert (
        boundary_relation("eq:15:percent:unknown", "gte:15:percent:list_price", "threshold")
        is None
    )
    assert boundary_relation("lte:35:days:elapsed", "lte:42:days:elapsed", "standard") == "qualify"
    assert (
        boundary_relation("eq:10:percent:list_price", "gte:15:percent:list_price", "threshold")
        == "contradict"
    )


def test_dates_do_not_invent_effectiveness_or_promote_model_dates():
    r = record()
    assert temporal_status(r, "2024-11-30")[0] == "no"
    assert temporal_status(r, "2025-01-01")[0] == "yes"
    assert temporal_status(r, "2026-01-01")[0] == "no"
    r["source"]["effective_start_date"] = None
    assert temporal_status(r, "2025-03-01")[0] == "unknown"
    assert temporal_status(r, "2025-03-01", frame(effective_start="2025-02-01"))[0] == "unknown"
    r["source"]["lifecycle_status"] = "draft"
    assert temporal_status(r, "2025-03-01")[0] == "no"


def test_graph_is_detached_assertions_not_authority_facts():
    r = record()
    units = units_for("Facilities Lead approves roof inspections.", "prescribed_rule", r)
    source = frame(
        actor="Facilities Lead",
        action="approve",
        object="roof_inspection",
        target="prescribed_rule",
    )
    for component in source.values():
        if isinstance(component, dict) and component["value"]:
            component["citations"] = [{"unit": "PASSAGE", "quote": r["text"]}]
    checked = validate_extraction({"claim": frame(), "assertions": [source]}, units)
    graph = assertion_graph(checked, r, "frozen-assessment")
    assert graph.graph["enabled"] is False
    assert {a["relationship"] for *_, a in graph.edges(data=True)} == {
        "EXTRACTED_FROM",
        "ASSERTED_IN",
        "COMPONENT_CITED_FROM",
    }
    assert any(a.get("assessment_target") == "prescribed_rule" for *_, a in graph.edges(data=True))
    assert "assessment=frozen-assessment" in graph.nodes["E-development"]["URL"]
    assert all(
        a.get("epistemic_status") == "model_proposed"
        for _, a in graph.nodes(data=True)
        if a["kind"] == "sourced_assertion"
    )
