"""Interpretation-1.3 structural, repair and provenance contracts."""

import json
from pathlib import Path

import pytest
from test_interpretation import API
from test_query_frames import adapter, frame, output

from decidr.approach_b import load_profile
from decidr.config import PROJ_ROOT
from decidr.interpretation import (
    InterpreterConfig,
    build_targeted_repair,
    merge_targeted_repair,
)
from decidr.query_frames import (
    FieldIssue,
    Interpretation,
    normalise_legacy_compound,
    normalise_legacy_interpretation,
)
from decidr.structural_normalization import arbitrate_target, grammar

SAVED = Path(__file__).parent / 'fixtures' / 'interpretation_1_2_saved_outputs.json'


def saved_benchmark():
    return json.loads(SAVED.read_text())


def saved_run(case_id):
    return saved_benchmark()[case_id]


@pytest.mark.parametrize(('question', 'action', 'obj', 'kind'), [
    ('When must an access pass be issued?', 'issue', 'an access pass', 'passive_to_active'),
    ('What procedure must staff follow to archive a research folder?', 'archive',
     'a research folder', 'purpose_infinitive'),
])
def test_generic_grammar_separates_operator_modal_and_action(question, action, obj, kind):
    result = grammar(question)
    assert result['business_action'] == action
    assert result['business_object'] == obj
    assert result['modality'] == 'must'
    assert result['transformation_type'] == kind


@pytest.mark.parametrize(('question', 'target'), [
    ('What must staff submit?', 'prescribed_rule'),
    ('What do staff normally submit?', 'actual_practice'),
    ('What value is stored in the database field?', 'recorded_state'),
])
def test_target_arbitration_uses_complete_question(question, target):
    assert arbitrate_target(question)[0] == target


def test_conflicting_target_signals_are_not_silently_resolved():
    target, signals = arbitrate_target('What must staff normally submit?')
    assert target == 'unknown'
    assert signals == ('actual_practice', 'prescribed_rule')


@pytest.mark.parametrize('case_id', ['DEV-03', 'DEV-10', 'DEV-12'])
def test_saved_failure_is_corrected_by_explicit_legacy_adapter(case_id):
    attempt = saved_run(case_id)[-1]
    result, records = normalise_legacy_interpretation(
        attempt['raw_content'], attempt['question'],
    )
    assert result.frames[0].answer_slots[0].value is None
    assert records and all(not record.protected_meaning_changed for record in records)


def test_saved_threshold_answer_slot_is_not_clarification_input():
    attempt = saved_run('DEV-03')[-1]
    result, records = normalise_legacy_interpretation(attempt['raw_content'], attempt['question'])
    item = result.frames[0]
    assert item.query_operator == 'threshold_lookup'
    assert item.answer_slots[0].binds_to == 'grammatical_subject'
    assert not item.needs_clarification and item.clarification_question is None
    assert any(record.transformation_type == 'requested_answer_not_missing_input'
               for record in records)


def test_saved_compound_inherits_context_and_normalises_passive_action():
    attempts = saved_run('DEV-07')
    question = 'Who approves renewals, and when must approval be obtained?'
    result, records = normalise_legacy_compound(
        [(attempt['question'], attempt['raw_content']) for attempt in attempts], question,
    )
    authority, timing = result.frames
    assert authority.business_action == 'approve'
    assert timing.business_action == 'obtain' and timing.modality == 'must'
    assert timing.process == 'renewals'
    assert timing.inherited_fields[0].source_fragment == 0
    assert any(record.transformation_type == 'unambiguous_compound_context_inheritance'
               for record in records)


@pytest.mark.parametrize(('question', 'action', 'obj'), [
    ('Who has custody of the access register?', 'has', 'custody of the access register'),
    ('Who retrieves archived invoices?', 'retrieve', 'archived invoices'),
    ('Who inquires about supplier status?', 'inquire', 'about supplier status'),
    ('Who checks access logs?', 'check', 'access logs'),
])
def test_explicit_business_actions_are_preserved(question, action, obj):
    item = frame(
        question,
        business_action=action,
        business_object=obj,
        process=None,
        source_spans=[],
    )
    result = adapter(API(output(item, question=question))).interpret(question)
    assert result.interpretation is not None
    assert result.interpretation.frames[0].business_action == action


@pytest.mark.parametrize('business_object', [None, ''])
def test_resolved_frame_rejects_incomplete_business_object(business_object):
    item = frame(business_object=business_object)
    with pytest.raises(ValueError):
        output_value = output(item)
        from decidr.query_frames import validate_interpretation

        validate_interpretation(json.dumps(output_value), item['original_question'])


def test_single_frame_preserves_multiple_requested_fields_and_null_slots():
    question = 'What threshold and timing govern discount approvals?'
    item = frame(
        question,
        query_operator='threshold_lookup',
        business_action='govern',
        business_object='discount approvals',
        process=None,
        requested_fields=['threshold', 'timing'],
        answer_slots=[
            {
                'requested_field': 'threshold',
                'binds_to': 'grammatical_subject',
                'value': None,
            },
            {'requested_field': 'timing', 'binds_to': 'temporal_scope', 'value': None},
        ],
        source_spans=[],
    )
    result = adapter(API(output(item, question=question))).interpret(question)
    assert result.interpretation is not None
    assert len(result.interpretation.frames) == 1
    result_frame = result.interpretation.frames[0]
    assert result_frame.requested_fields == ['threshold', 'timing']
    assert [slot.value for slot in result_frame.answer_slots] == [None, None]


def test_exact_date_survives_interpretation_1_3_path():
    question = 'As of 1 July 2026, does the previous approval policy still apply?'
    item = frame(
        question,
        query_operator='claim_verification',
        business_action='apply',
        business_object='the previous approval policy',
        process=None,
        requested_fields=['truth_status'],
        temporal_scope=['As of 1 July 2026'],
        source_spans=[],
    )
    result = adapter(API(output(item, question=question))).interpret(question)
    assert result.interpretation is not None
    assert result.interpretation.frames[0].temporal_scope == ['As of 1 July 2026']


@pytest.mark.parametrize('question', [
    'As of 1 May 2026, does the previous approval policy still apply?',
    'What approval status was recorded on May 1, 2026?',
])
def test_month_name_may_is_never_a_modal_verb(question):
    assert grammar(question)['modality'] is None


def test_null_string_recovery_is_deterministic_and_audited():
    item = frame(
        process='None',
        known_actor='null',
        scope='N/A',
        clarification_question='None',
        source_spans=[
            *frame()['source_spans'],
            {'field': 'process', 'text': 'None'},
        ],
    )
    result = adapter(API(output(item))).interpret(item['original_question'])
    assert result.interpretation is not None
    result_frame = result.interpretation.frames[0]
    assert (result_frame.process, result_frame.known_actor, result_frame.scope,
            result_frame.clarification_question) == (None, None, None, None)
    assert result.provenance['alignment_corrections'] == [
        {'frame': 0, 'field': field, 'code': 'null_representation'}
        for field in ('process', 'known_actor', 'scope', 'clarification_question')
    ] + [{
        'frame': 0,
        'field': 'process',
        'code': 'null_representation',
        'action': 'removed_absent_value_span',
    }]


def test_one_global_repair_budget_across_compound_fragments():
    question = 'Who approves it, and when must approval be obtained?'
    first_question = 'Who approves it'
    second_question = 'when must approval be obtained?'
    first_invalid = frame(
        first_question,
        business_action='approve',
        business_object='it',
        process=None,
        source_spans=[],
    )
    first_repair = {
        'frame_index': 0,
        'corrected_fields': {
            'assessment_target': 'unknown',
            'needs_clarification': True,
            'missing_material_fields': ['object referent'],
            'clarification_question': 'What does it refer to?',
        },
        'supporting_spans': [],
    }
    second_invalid = frame(
        second_question,
        query_operator='timing_lookup',
        business_action='obtain',
        business_object='approval',
        process=None,
        requested_fields=['timing'],
        modality=None,
        source_spans=[],
    )
    api = API(
        output(first_invalid, question=first_question),
        first_repair,
        output(second_invalid, question=second_question),
    )
    result = adapter(api).interpret(question)
    assert len(api.calls) == 3
    assert result.provenance['repair_attempted'] is True
    assert [item['repair_attempted'] for item in result.provenance['fragment_provenance']] == [
        True,
        False,
    ]


def test_adapter_receives_exact_bounded_context():
    context = tuple(f'context-{index}-' + ('x' * 2100) for index in range(6))
    expected = [text[:2000] for text in context[-4:]]
    api = API(output())
    adapter(api).interpret(frame()['original_question'], context)
    assert json.loads(api.calls[0]['messages'][1]['content']) == {
        'question': frame()['original_question'],
        'context': expected,
    }


def test_yaml_selected_model_and_environment_override(monkeypatch):
    profile = load_profile(PROJ_ROOT / 'configs' / 'approach_b_graph_llm.yaml')
    monkeypatch.delenv('DECIDR_INTERPRETER_MODEL', raising=False)
    assert InterpreterConfig.from_profile(profile).model == 'llama3.1:8b'
    monkeypatch.setenv('DECIDR_INTERPRETER_MODEL', 'fixture-override:latest')
    assert InterpreterConfig.from_profile(profile).model == 'fixture-override:latest'


@pytest.mark.parametrize('base_url', [
    'https://localhost:11434',
    'http://ollama.example:11434',
    'http://user:secret@localhost:11434',
    'http://localhost:11434/api',
    'http://localhost:11434?token=secret',
])
def test_interpretation_1_3_rejects_nonlocal_or_decorated_ollama_urls(base_url):
    with pytest.raises(ValueError, match='local HTTP base URL'):
        InterpreterConfig(base_url=base_url, model='fixture-model')


def test_valid_compound_fragment_survives_another_fragment_failure():
    question = 'Who approves reservations, and when must approval be obtained?'
    fragment = 'Who approves reservations'
    good = output(frame(
        fragment, business_action='approve', business_object='reservations',
        process='reservations', modality=None, source_spans=[],
    ), question=fragment)
    result = adapter(API(good, 'not json')).interpret(question)
    assert result.interpretation is None and result.provenance['fallback']
    assert len(result.partial_frames) == 1
    assert result.partial_frames[0].business_object == 'reservations'
    assert result.provenance['surviving_valid_frames']


def test_targeted_repair_request_contains_only_contract_fields():
    item = frame()
    issue = FieldIssue(frame_index=0, fields=['business_action'], code='invalid_action',
                       message='Use the underlying business action')
    request, locked = build_targeted_repair(
        item, [issue], item['original_question'], Interpretation.model_json_schema(),
    )
    assert set(request) == {
        'affected_frame', 'invalid_fields', 'field_validation_messages',
        'locked_validated_fields', 'relevant_original_question_spans', 'schema_definitions',
    }
    assert 'business_action' not in locked
    assert {'modality', 'polarity', 'numeric_values', 'temporal_scope'} <= locked


def test_targeted_repair_cannot_change_locked_protected_fields():
    item = frame()
    repair = json.dumps({
        'frame_index': 0,
        'corrected_fields': {'modality': 'may'},
        'supporting_spans': [],
    })
    with pytest.raises(ValueError):
        merge_targeted_repair(item, repair, {'business_action'}, {'modality'})


def test_targeted_repair_cannot_remove_explicit_entity_from_invalid_field():
    question = 'What threshold triggers Finance approval?'
    item = frame(
        question, query_operator='threshold_lookup', business_action='trigger',
        business_object='Finance approval', requested_fields=['threshold'],
        answer_slots=[{
            'requested_field': 'threshold', 'binds_to': 'grammatical_subject', 'value': None,
        }], source_spans=[],
    )
    repair = json.dumps({
        'frame_index': 0,
        'corrected_fields': {'business_object': 'approval'},
        'supporting_spans': [],
    })
    with pytest.raises(ValueError, match='protected meaning'):
        merge_targeted_repair(
            item, repair, {'business_object'}, set(), question,
        )


def test_targeted_repair_may_restore_invalid_modality_from_question():
    question = 'When must an access pass be issued?'
    item = frame(
        question, query_operator='timing_lookup', business_action='issue',
        business_object='an access pass', requested_fields=['timing'],
        answer_slots=[{
            'requested_field': 'timing', 'binds_to': 'temporal_scope', 'value': None,
        }], modality=None, source_spans=[],
    )
    repair = json.dumps({
        'frame_index': 0,
        'corrected_fields': {'modality': 'must'},
        'supporting_spans': [{
            'field': 'modality', 'text': 'must',
        }],
    })
    merged = merge_targeted_repair(item, repair, {'modality'}, set(), question)
    assert merged['modality'] == 'must'


def test_fallback_records_actual_proposal_and_confirmation_requirement():
    result = adapter(API(TimeoutError())).interpret('Who approves reservations?')
    provenance = result.provenance['fallback_provenance']
    assert provenance['fallback_parser_version']
    assert provenance['generated_frame']['business_object'] == 'reservations'
    assert provenance['reason_selected']
    assert 'legacy_parser_proposal' in provenance
    assert provenance['employee_confirmation_required'] is True


def test_targeted_repair_request_and_response_are_recorded():
    question = 'Who approves it?'
    invalid = frame(
        question, business_action='approve', business_object='it', process=None,
        assessment_target='prescribed_rule', source_spans=[],
    )
    repair = {
        'frame_index': 0,
        'corrected_fields': {
            'needs_clarification': True,
            'missing_material_fields': ['object referent'],
            'clarification_question': 'What does it refer to?',
        },
        'supporting_spans': [],
    }
    result = adapter(API(output(invalid, question=question), repair)).interpret(question)
    diagnostic = result.provenance['targeted_repair']
    assert result.interpretation and result.provenance['repair_attempted']
    assert set(diagnostic['request']) == {
        'affected_frame', 'invalid_fields', 'field_validation_messages',
        'locked_validated_fields', 'relevant_original_question_spans', 'schema_definitions',
    }
    assert json.loads(diagnostic['response']) == repair
