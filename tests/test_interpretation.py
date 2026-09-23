"""Synthetic interpretation contract tests; no organisational outcome evaluation."""

from copy import deepcopy
import json

import pytest

from decidr.interpretation_v1 import (
    InterpreterConfig, OllamaInterpreter, clarification_once, validate_interpretation,
)

QUESTION = "Who has formally documented authority to approve onboarding timeline extensions?"


def item(question=QUESTION, **updates):
    value = dict(
        original_question=question, intent="authority_lookup", subject=None,
        predicate="approve", object="onboarding timeline extensions", process="employee onboarding",
        scope=None, conditions=[], numeric_thresholds=[], temporal_scope=[], modality=None,
        polarity="positive", assessment_target="prescribed_rule", requested_field="authorised_role",
        needs_clarification=False, missing_material_fields=[], clarification_question=None,
        source_spans=[{"field": "predicate", "text": "approve"},
                      {"field": "object", "text": "onboarding timeline extensions"},
                      {"field": "process", "text": "onboarding"}],
    )
    return {**value, **updates}


def response(*items, question=QUESTION):
    return {"original_question": question, "items": list(items or [item()])}


class API:
    def __init__(self, *responses):
        self.responses = iter(responses)
        self.calls = []

    def __call__(self, payload):
        self.calls.append(deepcopy(payload))
        value = next(self.responses)
        if isinstance(value, Exception):
            raise value
        return {"message": {"content": value if isinstance(value, str) else json.dumps(value)}}


def run(api, question=QUESTION):
    return OllamaInterpreter(InterpreterConfig(), api).interpret(question)


def test_valid_structured_response_and_privacy_boundary():
    api = API(response())
    result = run(api)
    assert result.interpretation.items[0].object == "onboarding timeline extensions"
    assert result.proposal.claims[0].predicate == "approve"
    assert result.proposal.claims[0].evidence_target.value == "prescribed_rule"
    assert not result.provenance["fallback"]
    assert not result.provenance["repair_attempted"]
    payload = api.calls[0]
    assert payload["model"] == "llama3.2:latest"
    assert payload["stream"] is False and payload["options"]["temperature"] == 0
    assert payload["format"]["additionalProperties"] is False
    assert set(result.provenance) == {"model", "prompt_version", "schema_version", "latency_ms",
                                      "fallback", "repair_attempted", "status"}
    assert "corpus" not in json.loads(payload["messages"][1]["content"])


def test_malformed_repaired_once():
    api = API("not json", response())
    result = run(api)
    assert len(api.calls) == 2
    assert result.provenance["repair_attempted"] and not result.provenance["fallback"]
    repair = api.calls[1]["messages"]
    assert len(repair) == 1
    assert set(json.loads(repair[0]["content"])) == {
        "validation_errors", "previous_structured_response"}


def test_failed_repair_falls_back():
    api = API("broken", "still broken")
    result = run(api)
    assert len(api.calls) == 2 and result.provenance["fallback"]
    assert result.proposal.interpretation_source == "deterministic fallback"


@pytest.mark.parametrize("error", [ConnectionError("offline"), TimeoutError("timeout")])
def test_unavailable_and_timeout(error):
    api = API(error)
    assert run(api).provenance["fallback"]
    assert len(api.calls) == 1


@pytest.mark.parametrize("field,value", [
    ("verdict", "Supported"), ("confidence", "High"), ("credibility", 1),
    ("clarification_question", "None"), ("predicate", None), ("object", "extensions"),
    ("assessment_target", "recorded_state"),
    ("subject", "Invented Director"),
])
def test_rejects_extra_fields_placeholders_incomplete_action_and_wrong_target(field, value):
    with pytest.raises(ValueError):
        validate_interpretation(json.dumps(response(item(**{field: value}))), QUESTION)


def test_multiple_atomic_questions():
    second = "Who may approve travel?"
    other = item(second, object="travel", process=None, modality="may", source_spans=[
        {"field": "predicate", "text": "approve"}, {"field": "object", "text": "travel"},
        {"field": "modality", "text": "may"}])
    question = QUESTION + " " + second
    result = run(API(response(item(), other, question=question)), question)
    assert len(result.proposal.claims) == 2
    assert all(c.atomicity_status == "proposed_for_confirmation" for c in result.proposal.claims)


def test_explicit_threshold_and_date_survive_without_candidate_substitution(monkeypatch):
    from decidr.approach_b import ConstrainedClaimParser
    monkeypatch.setattr(ConstrainedClaimParser, "_portfolio_candidates",
                        lambda *args: pytest.fail("Valid local interpretation must not read portfolio"))
    question = "May engineers approve a 23% service adjustment after 2026-10-01?"
    value = item(question, intent="permission_check", subject="engineers", object="a 23% service adjustment",
                 process="service adjustment", modality="May", requested_field="truth_status",
                 numeric_thresholds=["23%"], temporal_scope=["after 2026-10-01"], source_spans=[
                     {"field": "predicate", "text": "approve"},
                     {"field": "object", "text": "a 23% service adjustment"},
                     {"field": "process", "text": "service adjustment"},
                     {"field": "roles", "text": "engineers"},
                     {"field": "subject", "text": "engineers"},
                     {"field": "modality", "text": "May"},
                     {"field": "numeric_thresholds", "text": "23%"},
                     {"field": "temporal_scope", "text": "after 2026-10-01"}])
    result = run(API(response(value, question=question)), question)
    assert not result.provenance["fallback"]
    assert result.proposal.claims[0].conditions == ["23%", "after 2026-10-01"]
    for updates in ({"numeric_thresholds": ["15%"]}, {"temporal_scope": []},
                    {"temporal_scope": ["after 2025-10-01"]}):
        with pytest.raises(ValueError):
            validate_interpretation(json.dumps(response({**value, **updates}, question=question)), question)


@pytest.mark.parametrize("question,intent,target,field,verb,obj", [
    ("What do operators actually do?", "actual_practice_lookup", "actual_practice",
     "practice_description", "do", "operators"),
    ("What value does the CRM contain?", "recorded_state_lookup", "recorded_state",
     "recorded_value", "contain", "value"),
    ("What value does the database contain?", "recorded_state_lookup", "recorded_state",
     "recorded_value", "contain", "value"),
])
def test_generic_assessment_targets(question, intent, target, field, verb, obj):
    value = item(question, intent=intent, assessment_target=target, requested_field=field,
                 predicate=verb, object=obj, process=None, source_spans=[
                     {"field": "predicate", "text": verb}, {"field": "object", "text": obj}])
    result = run(API(response(value, question=question)), question)
    assert result.proposal.claims[0].evidence_target.value == target
    value["assessment_target"] = "prescribed_rule"
    with pytest.raises(ValueError):
        validate_interpretation(json.dumps(response(value, question=question)), question)


def test_no_repeated_clarification():
    result = run(API(ConnectionError()))
    asked = set()
    first = clarification_once(result, asked)
    second = clarification_once(result, asked)
    assert first.proposal.clarification
    assert second.proposal.clarification is None
    assert second.proposal.requires_clarification  # Editing remains mandatory.


def test_disabled_and_explicit_no_fallback():
    api = API()
    assert OllamaInterpreter(InterpreterConfig(enabled=False), api).interpret(QUESTION).provenance["fallback"]
    assert not api.calls
    with pytest.raises(RuntimeError):
        OllamaInterpreter(InterpreterConfig(fallback="error"), API(TimeoutError())).interpret(QUESTION)


def test_phase1_excluded_and_unknown_process_insufficient(tmp_path):
    from decidr.approach_b import run_approach_b
    from decidr.database import connect, initialise_database
    from test_corpus_scope import _seed
    from decidr.models import ClaimOutcome

    path = tmp_path / "ledger.sqlite3"
    initialise_database(path)
    interpreted = run(API(response()))
    claim = interpreted.proposal.claims[0].model_copy(update={"atomicity_status": "user_confirmed"})
    profile = {"approach_id": "synthetic", "configuration_version": "test",
               "embedding_model": "unused", "cross_encoder_model": "unused"}
    with connect(path) as connection:
        _seed(connection, "phase1")
        result = run_approach_b(connection, QUESTION, claim, profile, "fixture")
        assert result.outcome == ClaimOutcome.INSUFFICIENT
        assert not result.citations
        assert connection.execute("SELECT COUNT(*) FROM claim_assessments").fetchone()[0] == 0


def test_local_url_only():
    with pytest.raises(ValueError):
        InterpreterConfig(base_url="https://hosted.example")


def test_streamlit_confirmation_keeps_local_model_outside_assessment(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest
    from decidr import config
    from decidr.config import PROJ_ROOT
    from decidr.database import initialise_database

    path = tmp_path / "ui.sqlite3"
    initialise_database(path)
    monkeypatch.setattr(config, "DATABASE_PATH", path)
    mock = run(API(response()))
    monkeypatch.setattr(OllamaInterpreter, "interpret", lambda self, question: mock)
    app = AppTest.from_file(str(PROJ_ROOT / "app/pages/10_Approach_B_Graph_and_LLM_Assistant.py"))
    app.run()
    app.chat_input[0].set_value(QUESTION).run()
    assert not app.exception
    assert app.session_state["approach_b_stage"] == "confirm"
    assert "approach_b_result" not in app.session_state
    next(b for b in app.button if b.label == "Confirm and assess").click().run()
    assert not app.exception
    assert app.session_state["approach_b_stage"] == "result"
    assert app.session_state["approach_b_result"].outcome.value == "Insufficient evidence"
    assert app.session_state["approach_b_technical_provenance"]["fallback"] is False
