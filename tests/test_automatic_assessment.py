"""Automatic results remain conditional and preserve immutable evidence for review."""

from contextlib import closing
from datetime import date
import importlib

from fastapi.testclient import TestClient
import pytest

from decidr.retrieval_models import Evidence, Source
from decidr.retrieval_store import (
    connect,
    initialise_database,
    replace_source_evidence,
    upsert_source,
)

api = importlib.import_module("decidr.api.app")
RULE = "Any discount of at least 20% off list price on a new-business deal requires written approval from Finance before the deal is marked won."
URL = "/api/corpus/assess-automatic"
SAVE = "/api/assessments/automatic"


@pytest.fixture
def setup(tmp_path, monkeypatch):
    # These tests pin the legacy deterministic engine; general-provider integration is separate.
    monkeypatch.setenv("DECIDR_ASSESSMENT_PROVIDER", "bounded")
    path = tmp_path / "corpus.sqlite"
    initialise_database(path)
    source = Source(
        source_id="s",
        title="Policy",
        original_file_path="policy.md",
        source_type="policy",
        checksum="a" * 64,
        ingestion_status="ingested",
        lifecycle_status="current",
        approval_status="Approved",
        effective_start_date=date(2025, 1, 1),
    )
    passage = Evidence(
        evidence_id="e",
        source_id="s",
        locator="p:1",
        text=RULE,
        source_type="policy",
        extraction_method="test",
    )

    def store():
        with closing(connect(path)) as connection, connection:
            upsert_source(connection, source)
            replace_source_evidence(connection, "s", [passage])

    store()
    monkeypatch.setenv("DECIDR_CORPUS_DB", str(path))
    monkeypatch.setenv("DECIDR_ASSESSMENT_DB", str(tmp_path / "history.sqlite"))
    previous = dict(api.app.dependency_overrides)
    api.app.dependency_overrides[api.auth.current_user] = lambda: {"id": 1}
    with TestClient(api.app) as client:
        yield client, source, passage, store
    api.app.dependency_overrides.clear()
    api.app.dependency_overrides.update(previous)


def body(**changes):
    return {"claim": RULE, "as_of": "2026-06-17", **changes}


def test_supported_wording_does_not_invent_authority(setup):
    client, _, passage, _ = setup
    response = client.post(URL, json=body())
    assert response.status_code == 200, response.text
    result = response.json()
    item = result["inputs"][0]
    assert item["interpretation"]["stance"] == "support"
    assert item["supplied_judgements"]["directness"] == 1
    assert item["supplied_judgements"]["authority_verified"] is None
    assert item["supplied_judgements"]["independence_verified"] is False
    assert not item["admitted_to_framework"]
    assert result["assessment"]["overall_outcome"] == "Insufficient evidence"
    citation = item["interpretation"]["citations"][0]
    assert passage.text[citation["start"] : citation["end"]] == citation["quotation"]
    assert result["assurance"]["human_review"] == "pending"


@pytest.mark.parametrize(
    "text",
    [
        RULE.replace("Finance", "Sales"),
        RULE.replace("at least 20%", "above 20%"),
        RULE + " Except for renewals.",
        "Written approval is required.",
    ],
)
def test_unsupported_comparisons_are_not_support_or_contradiction(setup, text):
    client, _, passage, store = setup
    passage.text = text
    store()
    result = client.post(URL, json=body()).json()
    assert all(
        x["interpretation"]["stance"] in {"unresolved", "context"} for x in result["inputs"]
    )
    assert result["assessment"]["overall_outcome"] == "Insufficient evidence"


def test_original_claim_optional_facet_and_no_matches(setup):
    client, *_ = setup
    original = "  My broader original claim.  "
    result = client.post(URL, json=body(claim=original, facet=RULE)).json()
    assert result["claim_text"] == original
    assert result["facet"] == RULE
    result = client.post(URL, json=body(claim="zzxqqzz")).json()
    assert result["inputs"] == []
    assert result["assessment"]["overall_outcome"] == "Insufficient evidence"


@pytest.mark.parametrize(
    "field,value",
    [
        ("derived_from_source_id", "missing-parent"),
        ("approval_status", "Not approved"),
        ("lifecycle_status", "draft"),
        ("effective_start_date", date(2027, 1, 1)),
        ("superseded_date", date(2026, 6, 17)),
    ],
)
def test_safeguards_retain_inputs_without_scoring(setup, field, value):
    client, source, _, store = setup
    setattr(source, field, value)
    store()
    response = client.post(URL, json=body())
    assert response.status_code == 200, response.text
    result = response.json()
    assert len(result["inputs"]) == 1
    assert not result["inputs"][0]["admitted_to_framework"]


def test_frozen_history_retry_and_review_revision(setup):
    client, _, passage, store = setup
    request = body(request_id="automatic-1")
    response = client.post(SAVE, json=request)
    assert response.status_code == 201, response.text
    saved = response.json()
    snapshot = saved["snapshot"]
    assert snapshot["record_type"] == "automatic_assessment"
    assert snapshot["response"]["persisted"] is True
    assert snapshot["interpretation"]["proposals"][0]["authority_context"]
    packet = snapshot["request"]
    packet["inputs"][0]["authority_verified"] = True
    packet["inputs"][0]["judgement_basis"] = "Synthetic reviewer authority assumption."
    reviewed = client.post(
        "/api/assessments",
        json={
            "request_id": "review-1",
            "assessment": packet,
            "parent_run_id": snapshot["run_id"],
            "revision_reason": "Review authority evidence",
        },
    )
    assert reviewed.status_code == 201, reviewed.text
    assert reviewed.json()["snapshot"]["response"]["assessment"]["overall_outcome"] == "Supported"
    summaries = {r["run_id"]: r for r in client.get("/api/assessments").json()["items"]}
    original = summaries[snapshot["run_id"]]
    revision = summaries[reviewed.json()["snapshot"]["run_id"]]
    assert original["record_type"] == "automatic_assessment"
    assert original["formal_outcome"] == snapshot["response"]["assessment"]["formal_outcome"]
    assert original["observed_outcome"] == snapshot["response"]["assessment"]["observed_outcome"]
    assert revision["parent_run_id"] == snapshot["run_id"]
    assert revision["overall_outcome"] == "Supported"
    assert original["overall_outcome"] == "Insufficient evidence"
    assert len(client.get("/api/assessments?limit=1&offset=1").json()["items"]) == 1
    passage.text = "Changed after assessment."
    store()
    assert (
        client.post(SAVE, json=request).json()
        == client.get("/api/assessments/" + snapshot["run_id"]).json()
    )
    assert (
        client.get("/api/assessments/" + snapshot["run_id"]).json()["snapshot"]["response"][
            "assessment"
        ]["overall_outcome"]
        == "Insufficient evidence"
    )
    assert {r["run_id"]: r for r in client.get("/api/assessments").json()["items"]} == summaries
    assert client.post(SAVE, json={**request, "claim": "different"}).status_code == 409
    api.app.dependency_overrides[api.auth.current_user] = lambda: {"id": 2}
    assert client.get("/api/assessments/" + snapshot["run_id"]).status_code == 404
    assert client.get("/api/assessments").json()["items"] == []


def test_request_validation_and_authentication(setup):
    client, *_ = setup
    for changes in ({"as_of": "tomorrow"}, {"claim": " "}, {"authority_verified": True}):
        assert client.post(URL, json=body(**changes)).status_code == 422
    api.app.dependency_overrides.pop(api.auth.current_user)
    assert client.post(URL, json=body()).status_code == 401
    assert client.post(SAVE, json=body(request_id="one")).status_code == 401


def test_matching_rule_with_compatible_surroundings_is_explained_and_frozen(setup):
    client, _, passage, store = setup
    passage.text = (
        "1. "
        + RULE
        + "\n2. Approval must be recorded in the CRM's `approval_record` field, referencing the approver and date."
        + "\n3. Discounts below 20% may be approved by the deal's Account Executive without further sign-off."
        + "\n4. This policy applies to new-business deals. Renewal discounting is governed separately by POL-06."
    )
    store()
    response = client.post(SAVE, json=body(request_id="context-regression"))
    assert response.status_code == 201, response.text
    saved = response.json()
    result = saved["snapshot"]["response"]
    assert result["rule_comparison"]["message"] == "Rule wording matches; authority unresolved"
    item = result["inputs"][0]
    assert item["interpretation"]["stance"] == "support"
    assert item["supplied_judgements"]["authority_verified"] is None
    assert not item["admitted_to_framework"]
    assert result["assessment"]["overall_outcome"] == "Insufficient evidence"
    context = result["proposals"][0]["passage_context"]
    assert context["compatible"]
    assert context["citation"]["quotation"] == passage.text
    quote = item["interpretation"]["citations"][0]
    assert passage.text[quote["start"] : quote["end"]] == quote["quotation"]
    passage.text += " Except for urgent deals."
    store()
    changed = client.post(URL, json=body()).json()
    assert changed["rule_comparison"]["status"] == "unresolved"
    assert changed["inputs"][0]["interpretation"]["stance"] == "unresolved"
    assert client.get("/api/assessments/" + saved["snapshot"]["run_id"]).json() == saved


@pytest.mark.parametrize("structured", [False, True, "expense", "renewal"])
def test_automatic_authority_chain_can_reach_supported_and_is_frozen(setup, structured):
    import os
    from pathlib import Path

    from test_authority_resolution import chain
    from test_expense_authority import expense_chain
    from test_renewal_cap import renewal_chain
    from test_structured_adoption import structured_chain

    sources, passages = (
        expense_chain()
        if structured == "expense"
        else structured_chain()
        if structured
        else chain()
    )
    if structured == "renewal":
        sources, passages = renewal_chain()
    client, _, _, _ = setup
    with closing(connect(Path(os.environ["DECIDR_CORPUS_DB"]))) as connection, connection:
        for source in sources.values():
            upsert_source(connection, source)
            replace_source_evidence(
                connection,
                source.source_id,
                [p for p in passages if p.source_id == source.source_id],
            )
    response = client.post(SAVE, json=body(claim=passages[0].text, request_id="authority-chain"))
    assert response.status_code == 201, response.text
    saved = response.json()
    result = saved["snapshot"]["response"]
    assert result["assessment"]["overall_outcome"] == "Supported"
    assert result["rule_comparison"]["status"] == "wording_matches_authority_resolved"
    policy = next(i for i in result["inputs"] if i["source"]["source_id"] == "test:POL-01")
    assert policy["admitted_to_framework"]
    assert policy["supplied_judgements"]["independence_verified"] is False
    proposal = next(p for p in result["proposals"] if p["source_id"] == "test:POL-01")
    assert proposal["authority_resolution"]["authority_verified"] is True
    assert proposal["authority_resolution"]["citations"]
    assert client.get("/api/assessments/" + saved["snapshot"]["run_id"]).json() == saved


def test_expense_api_preserves_citations_and_abstains_on_authority(setup):
    client, _, passage, store = setup
    rule = (
        "Expense claims over $500 require approval from Finance before reimbursement is processed."
    )
    passage.text = (
        "1. "
        + rule
        + "\n2. Expense claims of $500 or less may be approved by the employee's direct manager.\n3. All expense claims must include an itemised receipt."
    )
    store()
    response = client.post(SAVE, json=body(claim=rule, request_id="expense"))
    assert response.status_code == 201, response.text
    saved = response.json()
    result = saved["snapshot"]["response"]
    assert result["claim_text"] == rule
    item = result["inputs"][0]
    assert item["interpretation"]["stance"] == "support"
    assert not item["admitted_to_framework"]
    assert item["supplied_judgements"]["authority_verified"] is None
    assert item["supplied_judgements"]["independence_verified"] is False
    proposal = result["proposals"][0]
    assert proposal["authority_resolution"]["authority_verified"] is None
    assert not all(c["passed"] for c in proposal["authority_resolution"]["checks"])
    for c in item["interpretation"]["citations"]:
        assert passage.text[c["start"] : c["end"]] == c["quotation"]
    passage.text += " Except urgent claims."
    store()
    assert client.get("/api/assessments/" + saved["snapshot"]["run_id"]).json() == saved
    fresh = client.post(URL, json=body(claim=rule)).json()
    assert fresh["inputs"][0]["interpretation"]["stance"] == "unresolved"


@pytest.mark.parametrize("curly", [False, True])
def test_renewal_cap_saved_with_exact_context_and_unresolved_authority(setup, curly):
    from test_renewal_cap import CONTEXT
    from test_renewal_cap import RULE as CAP

    client, _, passage, store = setup
    passage.text = "1. " + CAP + CONTEXT
    store()
    claim = CAP.replace("account's", "account’s") if curly else CAP
    response = client.post(SAVE, json=body(claim=claim, request_id="renewal-cap"))
    assert response.status_code == 201, response.text
    saved = response.json()
    r = saved["snapshot"]["response"]
    assert r["claim_text"] == claim
    item = r["inputs"][0]
    assert item["interpretation"]["stance"] == "support"
    assert item["interpretation"]["mode"] == "formal"
    assert item["supplied_judgements"]["authority_verified"] is None
    assert not item["admitted_to_framework"]
    c = item["interpretation"]["citations"][0]
    assert passage.text[c["start"] : c["end"]] == c["quotation"]
    assert r["proposals"][0]["passage_context"]["compatible"]
    passage.text += " Exceptions may be approved by Sales."
    store()
    assert (
        client.post(URL, json=body(claim=CAP)).json()["inputs"][0]["interpretation"]["stance"]
        == "unresolved"
    )
    assert client.get("/api/assessments/" + saved["snapshot"]["run_id"]).json() == saved


@pytest.mark.parametrize("padding", ["", "\n\n"])
def test_deployment_rule_role_context_and_frozen_event_gap(setup, padding):
    from test_deployment_signoff import EVENT, audit
    from test_deployment_signoff import RULE as DEPLOY

    client, source, passage, store = setup
    source.source_type = "organisational_information"
    passage.source_type = "organisational_information"
    passage.heading = "Head of Engineering — Pat Jones"
    passage.text = DEPLOY.replace("Head of Engineering", "his")
    store()
    r = client.post(URL, json=body(claim=DEPLOY + padding)).json()
    assert r["claim_text"] == DEPLOY + padding
    assert r["inputs"][0]["interpretation"]["stance"] == "support"
    assert not r["inputs"][0]["admitted_to_framework"]
    assert r["proposals"][0]["authority_resolution"]["authority_verified"] is None
    source.source_type = "audit_events"
    passage.source_type = "audit_events"
    passage.text = audit().text
    store()
    response = client.post(SAVE, json=body(claim=EVENT, request_id="deployment-event"))
    assert response.status_code == 201, response.text
    saved = response.json()
    result = saved["snapshot"]["response"]
    assert result["assessment"]["overall_outcome"] == "Not assessed automatically"
    assert result["credibility_assessment"]["overall_outcome"] == "Insufficient evidence"
    assert result["deployment_event_findings"][0]["status"] == "unresolved"
    assert all(
        x["interpretation"]["stance"] not in {"support", "contradict"} for x in result["inputs"]
    )
    passage.text = "Changed record."
    store()
    assert client.get("/api/assessments/" + saved["snapshot"]["run_id"]).json() == saved


@pytest.mark.parametrize("verb", ["need approval from", "must be approved by"])
def test_automatic_paraphrase_keeps_original_citation_and_authority_gate(setup, verb):
    client, _, passage, store = setup
    passage.text = "Expense claims over €725 require approval from Regional Finance & Operations before reimbursement is processed."
    store()
    claim = passage.text.replace("require approval from", verb).replace(" & ", " and ")
    response = client.post(URL, json=body(claim=claim))
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["claim_text"] == claim
    item = result["inputs"][0]
    assert item["interpretation"]["mode"] == "formal"
    assert item["interpretation"]["stance"] == "support"
    citation = item["interpretation"]["citations"][0]
    assert passage.text[citation["start"] : citation["end"]] == citation["quotation"]
    assert not item["admitted_to_framework"]
    assert result["assessment"]["overall_outcome"] == "Insufficient evidence"


def test_automatic_difference_explains_field_without_inventing_contradiction(setup):
    client, _, _, _ = setup
    result = client.post(URL, json=body(claim=RULE.replace("Finance", "Sales"))).json()
    item = result["inputs"][0]
    assert item["interpretation"]["stance"] == "unresolved"
    assert "approver" in item["interpretation"]["rationale"]
    assert "does not prove contradiction" in item["interpretation"]["rationale"]


def test_practice_findings_scan_frozen_records_without_changing_formal_target(setup):
    import json

    client, source, passage, store = setup
    source.source_type = "project_tasks"
    passage.source_type = "project_tasks"
    passage.locator = "csv:row:2"
    passage.text = json.dumps(
        {
            "task_id": "UNSEEN-22",
            "process_or_capability": "Expense Approval",
            "expense_amount": "930",
            "currency": "€",
            "reimbursement_date": "2026-06-10",
            "payment_status": "reimbursed",
            "approval_date": "2026-06-12",
            "approval_role": "Regional Finance",
            "approval_status": "approved",
        }
    )
    store()
    claim = "Expense claims over €725 require approval from Regional Finance before reimbursement is processed."
    result = client.post(SAVE, json=body(claim=claim, request_id="practice-run")).json()
    response = result["snapshot"]["response"]
    assert response["assessment_target"] == "formal_rule"
    assert response["assessment"]["formal_outcome"] == "Insufficient evidence"
    finding = response["practice_assessment"]["findings"][0]
    assert finding["status"] == "recorded_departure"
    assert finding["citation"]["quotation"] == passage.text
    passage.text = "changed after saving"
    store()
    saved = client.get("/api/assessments/" + result["snapshot"]["run_id"]).json()
    assert saved == result


def test_transaction_claim_is_classified_and_saved_with_partial_result(setup):
    import json

    client, source, passage, store = setup
    source.source_type = passage.source_type = "crm_records"
    passage.row_identifier = "SALE-972"
    passage.locator = "csv:row:2"
    passage.text = json.dumps(
        {
            "deal_id": "SALE-972",
            "discount_pct": "32",
            "approval_role": "Alex Chen",
            "approval_record": "Approved via Slack",
            "close_date": "2026-04-02",
        }
    )
    store()
    claim = "SALE-972 Alex approved 32% discount before the contract was signed."
    saved = client.post(SAVE, json=body(claim=claim, request_id="transaction-run"))
    assert saved.status_code == 201, saved.text
    result = saved.json()
    response = result["snapshot"]["response"]
    assert response["claim_text"] == claim
    assert response["assessment_target"] == "underlying_event"
    assert "rule_comparison" not in response
    assert response["transaction_assessment"]["status"] == "partially_supported"
    assert response["transaction_assessment"]["citations"][0]["quotation"] == passage.text
    passage.text = "changed"
    store()
    assert client.get("/api/assessments/" + result["snapshot"]["run_id"]).json() == result


def test_connected_evidence_saved_with_exact_citations(setup):
    client, _, passage, _ = setup
    saved = client.post(SAVE, json=body(request_id="connected-run"))
    assert saved.status_code == 201, saved.text
    result = saved.json()
    report = result["snapshot"]["response"]["evidence_synthesis"]
    assert report["counts"]["formal"] == 1
    assert report["nodes"][0]["citation"]["quotation"] == passage.text
    assert client.get("/api/assessments/" + result["snapshot"]["run_id"]).json() == result


def test_record_primary_conclusion_consistent_with_history_and_separate_credibility(setup):
    import json

    client, source, passage, store = setup
    source.source_type = passage.source_type = "crm_records"
    passage.row_identifier = "SALE-972"
    passage.text = json.dumps(
        {
            "deal_id": "SALE-972",
            "discount_pct": "32",
            "approval_role": "Alex Chen",
            "approval_record": "Approved via Slack",
        }
    )
    store()
    saved = client.post(
        SAVE, json=body(claim="SALE-972 Alex approved 32% discount", request_id="conclusion-run")
    ).json()
    response = saved["snapshot"]["response"]
    assert response["claim_conclusion"]["status"] == "supported_by_records"
    assert response["assessment"]["overall_outcome"] == response["claim_conclusion"]["label"]
    assert response["credibility_assessment"]["overall_outcome"] == "Insufficient evidence"
    assert response["inputs"][0]["interpretation"]["stance"] == "support"
    assert "approval rule" not in response["inputs"][0]["interpretation"]["rationale"]
    rows = client.get("/api/assessments").json()["items"]
    assert rows[0]["claim_conclusion"] == response["claim_conclusion"]
    assert rows[0]["overall_outcome"] == response["assessment"]["overall_outcome"]
    assert client.get("/api/assessments/" + saved["snapshot"]["run_id"]).json() == saved


@pytest.mark.parametrize(
    "claim,changes,expected",
    [
        (
            "For SALE-972, the 32% discount was approved by Alex before signing.",
            {},
            "partially_supported",
        ),
        (
            "Alex authorised a 32% discount for SALE-972 before the contract was signed.",
            {},
            "partially_supported",
        ),
        (
            "SALE-972 Alex approved 32% discount",
            {"approval_status": "not approved", "approval_record": "Recorded in approvals"},
            "contradicted_by_records",
        ),
        (
            "SALE-972 Alex approved 32% discount",
            {"approval_status": "", "approval_record": "Awaiting sign-off"},
            "partially_supported",
        ),
    ],
)
def test_event_components_drive_primary_saved_and_list_outcomes(setup, claim, changes, expected):
    import json

    client, source, passage, store = setup
    source.source_type = passage.source_type = "crm_records"
    passage.row_identifier = "SALE-972"
    passage.text = json.dumps(
        {
            "deal_id": "SALE-972",
            "discount_pct": "32",
            "approval_role": "Alex Chen",
            "approval_status": "approved",
            **changes,
        }
    )
    store()
    saved = client.post(SAVE, json=body(claim=claim, request_id="event-regression")).json()
    r = saved["snapshot"]["response"]
    assert r["transaction_assessment"]["status"] == expected
    assert r["assessment"]["basis"] == "transaction_components_v1"
    assert r["assessment"]["overall_outcome"] == r["claim_conclusion"]["label"]
    assert r["assessment"]["components"] == r["transaction_assessment"]["components"]
    assert r["credibility_assessment"]["overall_outcome"] == "Insufficient evidence"
    assert all(
        "complete approval rule" not in i["interpretation"]["rationale"] for i in r["inputs"]
    )
    listed = client.get("/api/assessments").json()["items"][0]
    assert listed["overall_outcome"] == r["assessment"]["overall_outcome"]
    assert client.get("/api/assessments/" + saved["snapshot"]["run_id"]).json() == saved


@pytest.mark.parametrize(
    "scope,expected",
    [("All deal types", "supported_by_records"), ("Renewals only", "partially_supported")],
)
def test_no_id_channel_claim_with_optional_scope_saves_component_outcome(setup, scope, expected):
    import json

    client, source, passage, store = setup
    source.source_type = passage.source_type = "crm_records"
    passage.row_identifier = "SALE-972"
    passage.text = json.dumps(
        {
            "deal_id": "SALE-972",
            "discount_pct": "32",
            "approval_role": "Alex Chen (exception)",
            "approval_record": "Recorded outside CRM (Teams)",
            "notes": "Same-day exception approved by Alex — urgent request.",
            "close_date": "2026-04-02",
        }
    )
    store()
    claim = "Alex approved  32% discount on teams\n\n"
    facet = claim + "\n\nScope supplied by user: " + scope
    saved = client.post(SAVE, json=body(claim=claim, facet=facet, request_id="channel-event"))
    assert saved.status_code == 201, saved.text
    result = saved.json()
    response = result["snapshot"]["response"]
    assert response["claim_text"] == claim
    assert response["facet"] == facet
    assert response["transaction_assessment"]["status"] == expected
    assert response["assessment"]["overall_outcome"] == response["claim_conclusion"]["label"]
    assert response["assessment"]["basis"] == "transaction_components_v1"
    assert response["transaction_assessment"]["citations"][0]["quotation"] == passage.text
    assert client.get("/api/assessments/" + result["snapshot"]["run_id"]).json() == result


@pytest.mark.parametrize(
    "changes,expected",
    [
        ({}, "supported_by_records"),
        ({"contract_signed_date": ""}, "partially_supported"),
        ({"discount_pct": "9"}, "contradicted_by_records"),
        (
            {"approval_status": "pending", "approval_record": "Approved via email"},
            "conflicting_records",
        ),
        ({"approval_status": "not approved"}, "contradicted_by_records"),
    ],
)
def test_primary_result_matches_preview_snapshot_export_and_history(setup, changes, expected):
    import copy
    import json

    from decidr.assessment_history import content_hash

    client, source, passage, store = setup
    source.source_type = passage.source_type = "crm_records"
    passage.row_identifier = "ORDER-530"
    passage.text = json.dumps(
        {
            "deal_id": "ORDER-530",
            "discount_pct": "41",
            "approval_role": "Sam Patel",
            "approval_status": "approved",
            "approval_date": "2026-04-01",
            "contract_signed_date": "2026-04-03",
            **changes,
        }
    )
    store()
    query = body(
        claim="The 41% discount for ORDER-530 was authorised by Sam Patel before signing."
    )
    preview = client.post(URL, json=query).json()
    response = client.post(SAVE, json={**query, "request_id": "consistent-result"})
    assert response.status_code == 201, response.text
    saved = response.json()
    snapshot = saved["snapshot"]
    primary = snapshot["response"]["assessment"]
    assert snapshot["response"]["claim_conclusion"]["status"] == expected
    assert primary == preview["assessment"]
    assert snapshot["response"]["claim_conclusion"]["label"] == primary["overall_outcome"]
    summary = client.get("/api/assessments").json()["items"][0]
    assert (
        summary["overall_outcome"]
        == summary["claim_conclusion"]["label"]
        == primary["overall_outcome"]
    )
    run_id = snapshot["run_id"]
    assert client.get(f"/api/assessments/{run_id}/export").json() == saved
    assert content_hash(snapshot) == saved["snapshot_sha256"]
    packet = copy.deepcopy(snapshot["request"])
    packet["inputs"][0]["judgement_basis"] = "Reviewer retained unresolved source verification."
    revision = client.post(
        "/api/assessments",
        json={
            "request_id": "review-consistent-result",
            "parent_run_id": run_id,
            "revision_reason": "Reviewed recorded assertions without asserting authenticity.",
            "assessment": packet,
        },
    )
    assert revision.status_code == 201, revision.text
    assert revision.json()["snapshot"]["parent_snapshot_sha256"] == saved["snapshot_sha256"]
    passage.text = "Changed corpus content."
    store()
    assert client.get(f"/api/assessments/{run_id}/export").json() == saved


def test_component_evidence_missing_from_ranked_proposals_is_added_for_review(setup, monkeypatch):
    import json

    module = importlib.import_module("decidr.api.automatic_assessment")
    original = module.build_interpretation

    def drop_ranked_proposals(*args, **kwargs):
        draft = original(*args, **kwargs)
        draft["proposals"] = []
        return draft

    client, source, passage, store = setup
    source.source_type = passage.source_type = "crm_records"
    passage.row_identifier = "ORDER-530"
    passage.text = json.dumps(
        {
            "deal_id": "ORDER-530",
            "discount_pct": "41",
            "approval_role": "Sam Patel",
            "approval_status": "approved",
        }
    )
    store()
    monkeypatch.setattr(module, "build_interpretation", drop_ranked_proposals)
    r = client.post(URL, json=body(claim="ORDER-530 Sam Patel approved 41% discount")).json()
    assert r["claim_conclusion"]["status"] == "supported_by_records"
    assert len(r["inputs"]) == 1
    assert r["inputs"][0]["interpretation"]["stance"] == "support"
    assert r["inputs"][0]["interpretation"]["citations"][0]["quotation"] == passage.text


def test_unrecognised_event_is_interpretation_gap_not_an_evidence_verdict(setup):
    client, _, _, _ = setup
    result = client.post(
        SAVE,
        json=body(
            claim="Alex approved 32% discount and the customer paid in full.",
            assessment_target="underlying_event",
            request_id="unsupported-event",
        ),
    ).json()
    response = result["snapshot"]["response"]
    assert response["assessment"]["overall_outcome"] == "Not assessed automatically"
    assert response["claim_conclusion"]["status"] == "unsupported_interpretation"
    assert response["assurance"]["outcome_basis"] == "interpretation_incomplete"
    assert "rule_comparison" not in response
    assert all(
        "complete approval rule" not in item["interpretation"]["rationale"]
        for item in response["inputs"]
    )
    summary = client.get("/api/assessments").json()["items"][0]
    assert summary["overall_outcome"] == response["assessment"]["overall_outcome"]


@pytest.mark.parametrize(
    "deal_type,scope_status,scope_gate,outcome",
    [
        ("new business", "supported", True, "supported_by_records"),
        ("renewal", "contradicted", False, "contradicted_by_records"),
        (None, "unresolved", None, "partially_supported"),
    ],
)
def test_resolved_event_scope_and_graph_use_same_cited_record(
    setup, deal_type, scope_status, scope_gate, outcome
):
    import json

    client, source, passage, store = setup
    source.source_type = passage.source_type = "crm_records"
    passage.row_identifier = "ORDER-530"
    row = {
        "deal_id": "ORDER-530",
        "discount_pct": "41",
        "approval_role": "Sam Patel",
        "approval_status": "approved",
        "approval_record": "Recorded outside CRM (Teams)",
        "close_date": "2026-04-03",
    }
    if deal_type is not None:
        row["deal_type"] = deal_type
    passage.text = json.dumps(row)
    store()
    claim = "The 41% discount was authorised by Sam Patel on Teams."
    response = client.post(
        SAVE,
        json=body(
            claim=claim,
            facet=claim + "\n\nScope supplied by user: New-business deals",
            request_id="resolved-scope",
        ),
    )
    assert response.status_code == 201, response.text
    saved = response.json()
    result = saved["snapshot"]["response"]
    assert result["assessment_target"] == "underlying_event"
    transaction = result["transaction_assessment"]
    assert transaction["status"] == outcome
    scope = next(
        component for component in transaction["components"] if component["field"] == "scope"
    )
    assert scope["status"] == scope_status
    assert scope["observations"][0]["evidence_id"] == passage.evidence_id
    used_input = next(
        item
        for item in result["inputs"]
        if item["interpretation"]["citations"][0]["evidence_id"] == passage.evidence_id
    )
    assert used_input["supplied_judgements"]["scope_matches"] is scope_gate
    assert used_input["supplied_judgements"]["authority_verified"] is None
    assert used_input["supplied_judgements"]["independence_verified"] is False
    graph = result["evidence_synthesis"]
    assert any(
        node["lane"] == "documented" and node["record_id"] == "ORDER-530"
        for node in graph["nodes"]
    )
    assert all(node["citation"]["quotation"] == passage.text for node in graph["nodes"])
    if deal_type is None:
        assert "deal type" in scope["observations"][0]["reason"]
        assert "scope" in transaction["next_step"]
    listed = client.get("/api/assessments").json()["items"][0]
    assert listed["overall_outcome"] == result["assessment"]["overall_outcome"]
    assert (
        client.get("/api/assessments/" + saved["snapshot"]["run_id"] + "/export").json() == saved
    )
