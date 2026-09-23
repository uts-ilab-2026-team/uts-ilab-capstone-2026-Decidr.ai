"""Claim identity, automatic scope, and honest coverage regressions."""

from copy import deepcopy
import json

import pytest
from test_claim_first import ledger as ledger
from test_claim_first import seed
from test_claim_first_ui import page
from test_claim_first_ui import ui_ledger as ui_ledger
from test_conversation import TRAVEL
from test_conversation import travel_ledger as travel_ledger

from decidr.claim_export import claim_report_html
from decidr.claim_intake import interpret_claim
from decidr.claim_workflow import (
    _update_entry,
    ensure_system_assessment,
    entries,
    get_entry,
    get_run,
    review_interpretation,
    runs,
    submit_claim,
)
from decidr.conversation import (
    append_message,
    create_conversation,
    messages,
    send_message,
    sync_assessments,
)
from decidr.database import connect
from decidr.models import AtomicClaim


@pytest.mark.parametrize("reply", ["both", "all", "I want your interpretation"])
def test_all_scope_replies_proceed_and_preserve_snapshots(travel_ledger, reply):
    with connect(travel_ledger) as c:
        cid = create_conversation(c)
        send_message(c, cid, TRAVEL)
        first = deepcopy(get_run(c, messages(c, cid)[-1]["run_id"]))
        send_message(c, cid, reply)
        latest = get_run(c, messages(c, cid)[-1]["run_id"])
        assert latest["claim"]["evidence_target"] is None
        assert latest["claim"]["claim_text"] == TRAVEL
        assert latest["result"]["outcome"] == "Mixed findings"
        assert latest["result"]["policy_practice_divergence"]
        assert not [m for m in messages(c, cid) if m["kind"] == "question"]
        assert get_run(c, first["run_id"]) == first
        assert latest["result"]["review_status"] == "Not yet reviewed"


@pytest.mark.parametrize("reply", ["both", "all", "I want your interpretation"])
def test_saved_legacy_category_gate_with_prior_response_resumes(ledger, reply):
    with connect(ledger) as c:
        eid = submit_claim(c, "Support tickets are assigned to engineers.")[0]
        entry = get_entry(c, eid)
        entry["intake"].update(
            claim=None,
            status="awaiting_clarification",
            clarification="Is this about a prescribed rule, what happens in practice, or what a record says?",
        )
        entry["clarifications"] = [reply]
        _update_entry(c, eid, entry)
        c.execute(
            "UPDATE employee_claims SET claim_id=NULL,status='awaiting_clarification' WHERE entry_id=?",
            (eid,),
        )
        cid = create_conversation(c)
        append_message(c, cid, "user", "claim", entry["original_wording"], entry_id=eid)
        sync_assessments(c, cid)
        result = get_run(c, messages(c, cid)[-1]["run_id"])["result"]
        assert result["claim"]["evidence_target"] is None
        assert get_entry(c, eid)["clarifications"] == [reply]
        assert result["original_wording"] == entry["original_wording"]


@pytest.mark.parametrize(
    "discount",
    [
        "The threshold for new-business discount approval is 15%.",
        "Discount approval requires Finance.",
    ],
)
def test_pending_support_topic_does_not_contaminate_discount_exports(ledger, discount):
    with connect(ledger) as c:
        seed(c, "discount", text=discount)
        cid = create_conversation(c)
        send_message(c, cid, "They must close support tickets.")
        pending = deepcopy(entries(c)[0])
        send_message(c, cid, discount)
        run = get_run(c, messages(c, cid)[-1]["run_id"])
        assert get_entry(c, pending["entry_id"]) == pending
        assert messages(c, cid)[-1].get("parent_run_id") is None
        assert run["submission_original"] == run["claim"]["original_claim_text"] == discount
        assert run["claim"]["claim_text"] == run["packet"]["query"] == discount
        assert run["result"]["original_wording"] == discount
        assert "support tickets" not in claim_report_html(run["result"])
        assert "support tickets" not in json.dumps(run["result"])
        assert {r["evidence_id"] for r in run["packet"]["results"]} == {"E-discount"}
        send_message(c, cid, "Show sources")
        assert messages(c, cid)[-1]["run_id"] == run["run_id"]


def test_new_topic_and_revision_have_separate_identity(ledger):
    with connect(ledger) as c:
        cid = create_conversation(c)
        send_message(c, cid, "Support tickets are assigned to engineers.")
        original = deepcopy(runs(c)[0])
        send_message(c, cid, "Discount approval is required above 15%.")
        assert messages(c, cid)[-1].get("parent_run_id") is None
        discount = get_run(c, messages(c, cid)[-1]["run_id"])
        revised = "Discount approval is required above 20%."
        send_message(c, cid, revised)
        assert messages(c, cid)[-1]["parent_run_id"] == discount["run_id"]
        new = get_run(c, messages(c, cid)[-1]["run_id"])
        assert new["result"]["original_wording"] == revised
        assert new["parent_run_id"] == discount["run_id"]
        assert new["result"]["runtime_metadata"]["parent_run_id"] == discount["run_id"]
        assert new["claim"]["claim_id"] != discount["claim"]["claim_id"]
        assert get_run(c, original["run_id"]) == original


def test_shared_subject_does_not_make_a_new_process_a_revision(ledger):
    with connect(ledger) as c:
        cid = create_conversation(c)
        send_message(c, cid, "Employees must close support tickets.")
        send_message(c, cid, "Employees must approve discounts.")
        run = get_run(c, messages(c, cid)[-1]["run_id"])
        assert run["parent_run_id"] is None
        assert messages(c, cid)[-1].get("parent_run_id") is None


@pytest.mark.parametrize(
    "wording,target",
    [
        ("Support tickets are assigned to engineers.", None),
        ("The discount approval threshold is 15%.", None),
        ("The policy requires approval above 15%.", "prescribed_rule"),
        ("Discount approval is required above 15% in practice.", "actual_practice"),
        ("The CRM records approval above 15%.", "recorded_state"),
        ("The CRM records that employees must approve discounts.", "recorded_state"),
    ],
)
def test_explicit_scope_preserved_without_implicit_policy_default(wording, target):
    part = interpret_claim(wording).parts[0]
    assert part.claim and not part.clarification
    assert part.claim.evidence_target == target


def test_mixed_evidence_and_unclassified_candidate_are_distinct(ledger):
    claim = "The approval threshold is 15%."
    with connect(ledger) as c:
        seed(c, text=claim)
        seed(
            c,
            "practice",
            text=claim.replace("15%", "20%"),
            source_updates={"source_type": "interview"},
        )
        seed(
            c,
            "communication",
            text=claim.replace("15%", "20%"),
            source_updates={"source_type": "internal_communication"},
        )
        seed(c, "records", text=claim, source_updates={"source_type": "operational_record"})
        seed(c, "qualified", text="Possibly " + claim)
        seed(
            c,
            "unknown",
            text="The approval threshold involves a complex matrix of segment-dependent levels.",
        )
        run = ensure_system_assessment(c, submit_claim(c, claim)[0])
        result = run["result"]
        assert result["outcome"] == "Mixed findings"
        assert not any(r["kind"] == "contested_claim" for r in result["risk_flags"])
        assert result["target_findings"]["prescribed_rule"]["outcome"] == "Supported"
        assert result["target_findings"]["actual_practice"]["outcome"] == "Contradicted"
        assert result["target_findings"]["recorded_state"]["outcome"] == "Supported"
        assert result["qualifying_evidence"]
        assert result["classification_status"] == "incomplete"
        assert [e["evidence_id"] for e in result["unclassified_evidence"]] == ["E-unknown"]
        assert not result["evidence_gaps"]
        assert "provisional" in result["explanation"]
        html = claim_report_html(result)
        for target in ("Written rules", "Reported practice", "Recorded events"):
            assert target in html
        assert "E-unknown" in html and "unclassified" in html


def test_chat_shows_coverage_and_scoped_findings_before_review(ui_ledger):
    claim = "The approval threshold is 15%."
    with connect(ui_ledger) as c:
        seed(c, text=claim)
        seed(c, "unknown", text="The approval threshold involves a complex matrix.")
    app = page("assess_page", ui_ledger)
    app.chat_input[0].set_value(claim).run()
    assert not app.exception and not app.error
    assert any("Coverage is incomplete" in w.value for w in app.warning)
    assert any("Written rules: Supported" in m.value for m in app.markdown)
    assert any("Reported practice:" in m.value for m in app.markdown)
    assert any("Recorded events:" in m.value for m in app.markdown)
    assert not app.text_area and not app.text_input
    assert not any(s.label == "Meaning of the claim" for s in app.selectbox)


def test_available_claim_assessment_precedes_unresolved_reference(ledger):
    with connect(ledger) as c:
        cid = create_conversation(c)
        send_message(
            c, cid, "Engineers must inspect turbines within 48 hours. They must close tickets."
        )
        history = messages(c, cid)
        assert next(i for i, m in enumerate(history) if m["kind"] == "assessment") < next(
            i for i, m in enumerate(history) if m["kind"] == "question"
        )


def test_classifier_error_retains_findings_without_inventing_evidence_gap(ledger, monkeypatch):
    import decidr.automatic_evidence as classifier

    original = classifier._classify_evidence

    def fail_one(claim, record, run_id):
        if record["source_id"] == "failure":
            raise RuntimeError("Synthetic classifier failure")
        return original(claim, record, run_id)

    monkeypatch.setattr(classifier, "_classify_evidence", fail_one)
    with connect(ledger) as c:
        claim = "The approval threshold is 15%."
        seed(c, text=claim)
        seed(c, "failure", text=claim.replace("15%", "20%"))
        result = ensure_system_assessment(c, submit_claim(c, claim)[0])["result"]
        assert result["outcome"] == "Supported"
        assert result["supporting_evidence"]
        assert result["unclassified_evidence"][0]["failure_kind"] == "classifier_error"
        assert not result["evidence_gaps"]
        assert "provisional" in result["explanation"]
        assert result["review_status"] == "Not yet reviewed"


def test_coordinated_actions_do_not_require_parser_review(ledger):
    claim = "Engineers must inspect turbines and must log findings."
    with connect(ledger) as c:
        cid = create_conversation(c)
        send_message(c, cid, claim)
        result = get_run(c, messages(c, cid)[-1]["run_id"])["result"]
        assert result["original_wording"] == result["claim"]["claim_text"] == claim
        assert result["unclassified_evidence"]
        assert not result["evidence_gaps"]
        assert not any(m["kind"] == "question" for m in messages(c, cid))


def test_optional_interpretation_review_can_retain_all_evidence_scope(ledger):
    with connect(ledger) as c:
        wording = "Engineers inspect turbines."
        eid = submit_claim(c, wording)[0]
        review_interpretation(
            c,
            eid,
            AtomicClaim(
                claim_id="reviewed",
                subject="Engineers",
                predicate="inspect",
                object="turbines",
                claim_type="employee_entered",
                claim_text=wording,
                evidence_target=None,
            ),
            reviewer="Reviewer",
            reason="Literal action retained; assess all relevant evidence.",
        )
        result = ensure_system_assessment(c, eid)["result"]
        assert result["claim"]["evidence_target"] is None
        assert set(result["target_findings"]) == {
            "prescribed_rule",
            "actual_practice",
            "recorded_state",
        }


def test_scope_followup_keeps_original_reference_and_interpretation(ledger):
    with connect(ledger) as c:
        cid = create_conversation(c)
        original = "They must inspect turbines within 48 hours."
        send_message(c, cid, original)
        send_message(c, cid, "Engineers")
        resolved = deepcopy(get_run(c, messages(c, cid)[-1]["run_id"]))
        send_message(c, cid, "both")
        scoped = get_run(c, messages(c, cid)[-1]["run_id"])
        assert scoped["result"]["original_wording"] == original
        assert scoped["claim"]["original_claim_text"] == original
        assert scoped["claim"]["claim_text"] == resolved["claim"]["claim_text"]
        assert (
            scoped["interpretation_provenance"]["prior_interpretation"]
            == resolved["interpretation_provenance"]
        )
        assert get_run(c, resolved["run_id"]) == resolved
