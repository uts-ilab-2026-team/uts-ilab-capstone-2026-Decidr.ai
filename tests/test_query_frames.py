"""Mocked interpretation-1.3 query frames; no model or formal evaluation."""

import json

import pytest
from test_interpretation import API, QUESTION

from decidr.interpretation import (
    InterpreterConfig,
    OllamaInterpreter,
    QueryConversation,
    clarification_once,
)
from decidr.query_frames import AtomicClaim, validate_interpretation
from decidr.structural_normalization import (
    answer_binding,
    grammar,
    query_operator,
    requested_field,
)


def frame(question=QUESTION, **updates):
    structure = grammar(question)
    operator = updates.pop('query_operator', query_operator(question))
    requested = updates.pop('requested_fields', [requested_field(operator)])
    value = {
        'original_question': question,
        'query_operator': operator,
        'business_action': structure['business_action'] or 'approve',
        'business_object': structure['business_object'] or 'onboarding timeline extensions',
        'known_actor': structure['known_actor'],
        'requested_fields': requested,
        'answer_slots': [
            {'requested_field': item, 'binds_to': answer_binding(item, question), 'value': None}
            for item in requested
        ],
        'modality': structure['modality'],
        'process': 'onboarding',
        'assessment_target': updates.pop('assessment_target', 'prescribed_rule'),
        'scope': None,
        'conditions': [],
        'numeric_values': [],
        'temporal_scope': [],
        'polarity': 'positive',
        'source_spans': structure['supporting_source_spans'],
        'needs_clarification': False,
        'missing_material_fields': [],
        'clarification_question': None,
        'inherited_fields': [],
    }
    return {**value, **updates}


def output(*frames, question=QUESTION):
    return {'original_question': question, 'frames': list(frames or [frame(question)])}


def adapter(api):
    return OllamaInterpreter(InterpreterConfig(model='mock-development-model'), api)


def parsed(value=None, question=QUESTION, context=()):
    return validate_interpretation(json.dumps(value or output(question=question)), question, context)


def permission():
    question = 'Can sales employees approve a 20% new-business discount without a manager?'
    return question, frame(
        question,
        business_action='approve',
        business_object='a 20% new-business discount without a manager',
        process=None,
        known_actor='sales employees',
        requested_fields=['truth_status'],
        numeric_values=['20%'],
        conditions=['without a manager'],
        source_spans=[],
    )


def ambiguous():
    question = 'Who approves it?'
    return question, frame(
        question,
        business_action='approve',
        business_object='it',
        process=None,
        assessment_target='unknown',
        needs_clarification=True,
        missing_material_fields=['object referent'],
        clarification_question='What does “it” refer to?',
    )


def multiple():
    question = 'Who approves renewals, and when must approval be obtained?'
    authority = frame(
        question, query_operator='authority_lookup', business_action='approve',
        business_object='renewals', process='renewals', requested_fields=['authorised_role'],
        modality=None, source_spans=[],
    )
    timing = frame(
        question, query_operator='timing_lookup', business_action='obtain',
        business_object='approval', process='renewals', modality='must',
        requested_fields=['timing'], source_spans=[],
    )
    return question, authority, timing


def test_authority_is_query_with_unknown_actor_and_answer_slot():
    result = adapter(API(output())).interpret(QUESTION)
    item = result.interpretation.frames[0]
    assert item.known_actor is None and item.query_operator == 'authority_lookup'
    assert item.business_action == 'approve'
    assert item.business_object == 'onboarding timeline extensions'
    assert item.answer_slots[0].model_dump() == {
        'requested_field': 'authorised_role', 'binds_to': 'known_actor', 'value': None,
    }
    assert result.provenance['schema_version'] == 'interpretation-1.3'
    assert not isinstance(item, AtomicClaim)


@pytest.mark.parametrize('extra', [
    {'verdict': 'Supported'}, {'confidence': 1}, {'predicate': 'approve'},
    {'intent': 'authority_lookup'},
])
def test_legacy_or_outcome_fields_are_not_silently_accepted(extra):
    with pytest.raises(ValueError):
        parsed(output({**frame(), **extra}))


def test_requested_answer_cannot_trigger_clarification_or_have_value():
    question = 'What threshold requires approval?'
    item = frame(
        question, business_action='require', business_object='approval', process='approval',
        requested_fields=['threshold'], source_spans=[],
    )
    assert parsed(output(item, question=question), question).frames[0].answer_slots[0].value is None
    for changes in (
        {'needs_clarification': True, 'missing_material_fields': ['threshold'],
         'clarification_question': 'What threshold?'},
        {'answer_slots': [{'requested_field': 'threshold', 'binds_to': 'grammatical_subject',
                           'value': '20%'}]},
    ):
        with pytest.raises(ValueError):
            parsed(output({**item, **changes}, question=question), question)


def test_permission_preserves_actor_exclusion_and_number():
    question, item = permission()
    value = parsed(output(item, question=question), question).frames[0]
    assert value.known_actor == 'sales employees'
    assert value.numeric_values == ['20%'] and value.modality == 'can'
    for changes in ({'known_actor': None}, {'numeric_values': []},
                    {'numeric_values': ['25%']}, {'conditions': []},
                    {'modality': 'must'}, {'assessment_target': 'actual_practice'}):
        with pytest.raises(ValueError):
            parsed(output({**item, **changes}, question=question), question)


@pytest.mark.parametrize(('question', 'target', 'wrong_target', 'action', 'obj'), [
    ('Do employees normally record approvals in Slack?', 'actual_practice', 'recorded_state',
     'record', 'approvals in Slack'),
    ('What value is stored in the CRM field?', 'recorded_state', 'prescribed_rule',
     'store', 'value'),
    ('When must access be recorded?', 'prescribed_rule', 'actual_practice',
     'record', 'access'),
])
def test_complete_question_target_arbitration(question, target, wrong_target, action, obj):
    item = frame(
        question, business_action=action, business_object=obj, assessment_target=target,
        process=None, source_spans=[],
    )
    assert parsed(output(item, question=question), question).frames[0].assessment_target == target
    with pytest.raises(ValueError, match='assessment_target'):
        parsed(output({**item, 'assessment_target': wrong_target}, question=question), question)


def test_conflicting_target_signals_require_confirmation():
    question = 'What must employees normally do?'
    from decidr.structural_normalization import arbitrate_target

    assert arbitrate_target(question) == ('unknown', ('actual_practice', 'prescribed_rule'))


def test_multiple_items_are_confirmed_separately():
    question, authority, timing = multiple()
    value = parsed(output(authority, timing, question=question), question)
    assert [item.requested_fields for item in value.atomic_frames()] == [
        ['authorised_role'], ['timing'],
    ]


def test_compound_rejects_missing_duplicated_and_silently_merged_frames():
    question, authority, timing = multiple()
    merged = {
        **authority,
        'business_object': 'renewals, and when must approval be obtained',
        'requested_fields': ['authorised_role', 'timing'],
        'answer_slots': [authority['answer_slots'][0], timing['answer_slots'][0]],
        'source_spans': [],
    }
    for candidate in (
        output(authority, question=question),
        output(authority, timing, timing, question=question),
        output(merged, question=question),
    ):
        with pytest.raises(ValueError):
            parsed(candidate, question)


def test_recorded_identifier_is_not_a_numeric_threshold():
    question = 'What approval value is recorded for DEAL-041?'
    item = frame(
        question,
        query_operator='recorded_state_lookup',
        business_action='record',
        business_object='approval value',
        process=None,
        assessment_target='recorded_state',
        requested_fields=['recorded_value'],
        conditions=['for DEAL-041'],
        source_spans=[],
    )
    value = parsed(output(item, question=question), question).frames[0]
    assert value.conditions == ['for DEAL-041'] and value.numeric_values == []
    with pytest.raises(ValueError, match='identifier|numeric'):
        parsed(
            output({**item, 'conditions': [], 'numeric_values': ['DEAL-041']}, question=question),
            question,
        )


def test_context_resolution_and_no_repeated_clarification():
    question, item = ambiguous()
    first = adapter(API(output(item, question=question))).interpret(question)
    asked = set()
    assert clarification_once(first, asked).clarification_prompts
    assert not clarification_once(first, asked).clarification_prompts
    reply = 'The warehouse lease extension.'
    resolved = {
        **item,
        'business_object': 'warehouse lease extension',
        'process': 'warehouse lease extension',
        'assessment_target': 'prescribed_rule',
        'needs_clarification': False,
        'missing_material_fields': [],
        'clarification_question': None,
        'source_spans': [
            {'field': 'business_action', 'text': 'approves'},
            {'field': 'business_object', 'text': 'warehouse lease extension', 'context_index': 0},
            {'field': 'process', 'text': 'warehouse lease extension', 'context_index': 0},
        ],
    }
    conversation = QueryConversation(question, interpretation=first.interpretation)
    conversation, result = conversation.clarify(
        reply, adapter(API(output(resolved, question=question))),
    )
    assert conversation.interpretation.frames[0].business_object == 'warehouse lease extension'
    assert not clarification_once(result, asked).clarification_prompts


def test_confirmation_component_renders_every_atomic_item():
    from app.query_frame_confirmation import render_query_frames
    from streamlit.testing.v1 import AppTest

    question, authority, timing = multiple()
    value = parsed(output(authority, timing, question=question), question)

    def app(payload):
        from app.query_frame_confirmation import render_query_frames

        from decidr.query_frames import Interpretation

        render_query_frames(Interpretation.model_validate_json(payload))

    test = AppTest.from_function(app, args=(value.model_dump_json(),)).run()
    assert not test.exception
    assert len([button for button in test.button if button.label.startswith('Confirm item')]) == 2
    assert callable(render_query_frames)
