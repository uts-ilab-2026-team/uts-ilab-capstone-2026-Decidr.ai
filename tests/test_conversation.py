"""Conversation continuity and evidence isolation on synthetic and actual sources."""

from copy import deepcopy
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from test_claim_first import CLAIM, ledger, seed  # noqa: F401
from test_claim_first_ui import page, ui_ledger, widget  # noqa: F401

from decidr.claim_workflow import (
    entries,
    get_entry,
    get_run,
    initialise_workflow,
    reassess_evidence,
    runs,
    submit_claim,
)
from decidr.conversation import (
    create_conversation,
    followup_kind,
    messages,
    reopen_claim,
    send_message,
    sync_assessments,
)
from decidr.database import connect
from decidr.ingestion import ingest

TRAVEL = "Customer-onboarding travel follows the normal expense approval route."


def test_history_is_not_evidence_and_changed_claim_links_new_snapshot(ledger):
    with connect(ledger) as c:
        cid = create_conversation(c)
        send_message(c, cid, CLAIM)
        original = deepcopy(runs(c)[0])
        for query in ["Show sources", "What contradicts this?", "Any exceptions?", "Why?"]:
            send_message(c, cid, query)
            response = messages(c, cid)[-1]
            assert response["run_id"] == original["run_id"]
            assert set(response["evidence_ids"]) <= {
                r["evidence_id"] for r in original["result"]["evidence_records"]
            }
        assert len(runs(c)) == 1
        revised = "Engineers must inspect turbines within 72 hours."
        send_message(c, cid, revised)
        assert len(runs(c)) == 2
        assert runs(c)[0] == original
        latest = messages(c, cid)[-1]
        assert latest["parent_run_id"] == original["run_id"]
        new = get_run(c, latest["run_id"])
        assert new["claim"]["claim_text"] == new["packet"]["query"] == revised
        assert {r["evidence_id"] for r in new["result"]["evidence_records"]} == {"E-S1"}
        count = len(messages(c, cid))
        sync_assessments(c, cid)
        assert len(messages(c, cid)) == count
        assert reopen_claim(c, original["entry_id"]) == cid
    with connect(ledger) as c:
        assert len(messages(c, cid)) == count
        assert get_run(c, original["run_id"]) == original


@pytest.mark.parametrize(
    "text",
    [
        "What if only managers approve expenses?",
        "Exceptions must be approved by Finance.",
        "Sources say Engineers must inspect turbines within 72 hours.",
        "What about exceptions for international travel?",
    ],
)
def test_changed_or_unbounded_followups_never_reuse_a_verdict(text):
    assert followup_kind(text) is None


def test_failed_turn_rolls_back_and_cross_conversation_links_are_rejected(ledger, monkeypatch):
    import decidr.conversation as chat

    with connect(ledger) as c:
        cid = create_conversation(c)
        original = chat.ensure_system_assessment
        monkeypatch.setattr(
            chat,
            "ensure_system_assessment",
            lambda *a: (_ for _ in ()).throw(ValueError("failure")),
        )
        with pytest.raises(ValueError, match="failure"):
            send_message(c, cid, CLAIM)
        assert not messages(c, cid) and not entries(c) and not runs(c)
        monkeypatch.setattr(chat, "ensure_system_assessment", original)
        send_message(c, cid, CLAIM)
        other = create_conversation(c)
        with pytest.raises(ValueError, match="from this conversation"):
            send_message(c, other, "Sources?", linked_run_id=runs(c)[0]["run_id"])
        assert not messages(c, other)


@pytest.fixture(scope="module")
def travel_ledger(tmp_path_factory):
    path = tmp_path_factory.mktemp("travel-chat") / "ledger.sqlite"
    ingest({"phase2": Path("data/raw/phase2_model_development")}, path)
    with connect(path) as c:
        initialise_workflow(c)
    return path


@pytest.mark.parametrize(
    "target,outcome", [("Written policy", "Supported"), ("Actual practice", "Contradicted")]
)
def test_travel_context_target_and_real_evidence(travel_ledger, target, outcome):
    with connect(travel_ledger) as c:
        cid = create_conversation(c)
        send_message(c, cid, TRAVEL)
        first = get_run(c, messages(c, cid)[-1]["run_id"])
        assert first["result"]["outcome"] == "Mixed findings"
        assert first["claim"]["evidence_target"] is None
        assert not [m for m in messages(c, cid) if m["kind"] == "question"]
        send_message(c, cid, target)
        response = messages(c, cid)[-1]
        run = get_run(c, response["run_id"])
        assert run["result"]["outcome"] == outcome
        entry = get_entry(c, response["entry_id"])
        assert entry["original_wording"] == run["claim"]["claim_text"] == TRAVEL
        assert run["claim"]["predicate"] == "follows"
        assert entry["intake"]["provenance"]["interpreted_claim"] == TRAVEL
        assert entry["intake"]["provenance"]["terminology_context"]
        assert get_run(c, first["run_id"]) == first
        notes = run["result"]["review_snapshot"]
        if target == "Written policy":
            assert any(
                e["source_id"] == "phase2:POL-07" for e in run["result"]["supporting_evidence"]
            )
            assert any(
                "pre-approval" in n["classification"]["reason"]
                and n["link"]["relationship"] == "contextual"
                for n in notes.values()
            )
        else:
            assert all(
                notes[e["evidence_id"]]["credibility"]["evidence_mode"] == "observed_practice"
                for e in run["result"]["contradicting_evidence"]
            )
        send_message(c, cid, "Any exceptions?")
        assert messages(c, cid)[-1]["run_id"] == run["run_id"]


def test_human_reassessment_appends_without_changing_original_or_followup(ledger):
    with connect(ledger) as c:
        cid = create_conversation(c)
        send_message(c, cid, CLAIM)
        original = deepcopy(runs(c)[0])
        send_message(c, cid, "Sources?")
        before = deepcopy(messages(c, cid))
        note = original["result"]["review_snapshot"]["E-S1"]
        reviewed = reassess_evidence(
            c,
            original["run_id"],
            "E-S1",
            reviewer="Fixture reviewer",
            rationale="Confirmed against source",
            relationship="support",
            matches={
                key: True
                for key in ("target_match", "scope_match", "condition_match", "temporal_match")
            },
            mode="formal_rule",
            dimensions={
                key: note["credibility"][key]
                for key in (
                    "relevance",
                    "institutional_authority",
                    "directness",
                    "temporal_validity",
                    "independence",
                    "completeness",
                    "organisational_applicability",
                )
            },
            justification="Confirmed source",
            applicability_reason="Exact scoped rule",
        )
        sync_assessments(c, cid)
        assert messages(c, cid)[:-1] == before
        assert messages(c, cid)[-1]["run_id"] == reviewed["run_id"]
        assert get_run(c, original["run_id"]) == original


def test_chat_ui_followup_reopen_and_frozen_source(ui_ledger, monkeypatch):
    app = page("assess_page", ui_ledger)
    assert len(app.chat_input) == 1 and not app.text_input and not app.text_area
    app.chat_input[0].set_value(CLAIM).run()
    assert not app.exception and not app.error
    cid = app.query_params["conversation"][0]
    assert widget(app.metric, "Verdict").value == "Supported"
    assert not app.text_input and not app.text_area
    app.chat_input[0].set_value("Show sources").run()
    assert not app.exception and len(app.chat_message) == 4
    source_link = next(b.proto.url for b in app.get("link_button") if b.label == "Open source")
    params = parse_qs(urlsplit(source_link).query)
    assert params["conversation"] == [cid] and params["assessment"] and params["evidence"]
    with connect(ui_ledger) as c:
        seed(c, text="The live source was changed after assessment.")
    # A fresh session exercises URL-based reopening and the actual source renderer.
    from streamlit.testing.v1 import AppTest
    from test_claim_first_ui import harness

    import decidr.config

    monkeypatch.setattr(decidr.config, "DATABASE_PATH", ui_ledger)
    source = AppTest.from_file(str(Path("app/Home.py").resolve()))
    source.query_params.update({k: v[0] for k, v in params.items()})
    source.run()
    assert not source.exception
    assert any(t.value == CLAIM for t in source.text)
    assert not any("live source was changed" in t.value for t in source.text)
    widget(source.button, "Return to claim assessment").click().run()
    assert not source.exception and len(source.chat_message) == 4
    reopened = AppTest.from_function(harness, args=("assess_page", str(ui_ledger)))
    reopened.query_params["conversation"] = cid
    reopened.run()
    assert not reopened.exception and len(reopened.chat_message) == 4
    assert widget(reopened.metric, "Verdict").value == "Supported"
    widget(reopened.button, "New conversation").click().run()
    assert not reopened.exception and not reopened.chat_message
    widget(reopened.selectbox, "Saved conversations").select(cid).run()
    assert not reopened.exception and len(reopened.chat_message) == 4


@pytest.mark.parametrize("answer", ["Engineers", "They refers to Engineers."])
def test_short_reference_clarification_is_explicit_and_audited(ledger, answer):
    with connect(ledger) as c:
        cid = create_conversation(c)
        send_message(c, cid, "They must inspect turbines within 48 hours.")
        send_message(c, cid, answer)
        run = get_run(c, messages(c, cid)[-1]["run_id"])
        assert run["claim"]["claim_text"] == CLAIM
        assert run["claim"]["original_claim_text"] == "They must inspect turbines within 48 hours."
        entry = get_entry(c, run["entry_id"])
        assert entry["clarifications"] == [answer]
        assert entry["intake"]["provenance"]["meaning_basis"] == "explicit_user_reference"


def test_multi_claim_has_one_user_message_and_separate_assessments(ledger):
    with connect(ledger) as c:
        cid = create_conversation(c)
        text = CLAIM + " Operators must close valves."
        send_message(c, cid, text)
        history = messages(c, cid)
        assert [m["text"] for m in history if m["role"] == "user"] == [text]
        assert len([m for m in history if m["kind"] == "assessment"]) == 2


def test_policy_followup_retains_practice_contradiction_as_context(travel_ledger):
    with connect(travel_ledger) as c:
        cid = create_conversation(c)
        send_message(c, cid, TRAVEL)
        send_message(c, cid, "I mean written policy")
        baseline = get_run(c, messages(c, cid)[-1]["run_id"])
        send_message(c, cid, "Which sources contradict this claim?")
        answer = messages(c, cid)[-1]
        assert answer["evidence_ids"]
        assert any(
            baseline["result"]["review_snapshot"][eid]["link"]["relationship"] == "contextual"
            for eid in answer["evidence_ids"]
        )


def test_route_comparison_requires_explicit_scope_and_unmodified_claim(travel_ledger):
    from decidr.automatic_evidence import classify_evidence
    from decidr.models import AtomicClaim

    with connect(travel_ledger) as c:
        cid = create_conversation(c)
        send_message(c, cid, TRAVEL)
        send_message(c, cid, "Written policy")
        run = get_run(c, messages(c, cid)[-1]["run_id"])
    claim = AtomicClaim.model_validate(run["claim"])
    record = next(
        r
        for r in run["packet"]["results"]
        if r["source_id"] == "phase2:POL-07" and "Formal requirements" in r["locator"]
    )
    assert (
        classify_evidence(claim, {**record, "source_context": []}, "test")["link"]["relationship"]
        != "support"
    )
    changed = claim.model_copy(update={"claim_text": TRAVEL.rstrip(".") + " without receipts."})
    assert classify_evidence(changed, record, "test")["link"]["relationship"] != "support"
