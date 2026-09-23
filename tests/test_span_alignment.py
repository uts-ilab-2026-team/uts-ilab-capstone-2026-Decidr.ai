"""Generic span alignment and protected-value regression tests."""

import json

import pytest
from test_interpretation import QUESTION
from test_query_frames import frame, output, permission

from decidr.query_frames import validate_interpretation
from decidr.span_alignment import CriticalInterpretationError, align


@pytest.mark.parametrize(('value', 'source', 'method'), [
    ('reading booth', 'Reserve a reading booth.', 'exact'),
    ('RESERVE', 'Reserve a reading booth.', 'case_insensitive'),
    ('cafe permits', 'Café—permits', 'unicode_punctuation'),
    ('permit approvals', 'approve permits', 'token_alignment'),
])
def test_generic_alignment_stages(value, source, method):
    start, end, actual, score = align(value, source)
    assert source[start:end] and actual == method and score >= .85


@pytest.mark.parametrize(('value', 'source'), [
    ('20%', '25%'),
    ('2026-01-10', '2026-10-01'),
    ('before 2026-10-01', 'after 2026-10-01'),
    ('must', 'may'),
    ('not permitted', 'permitted'),
    ('director', 'employees'),
    ('supplier rebate bankruptcy', 'supplier rebate approval'),
])
def test_alignment_cannot_introduce_facts_or_change_protected_tokens(value, source):
    with pytest.raises(CriticalInterpretationError):
        align(value, source)


def test_score_threshold_is_configurable():
    with pytest.raises(CriticalInterpretationError):
        align('authorisation', 'authorization', threshold=1)


def test_normalised_lemma_aligns_to_complete_source_token():
    source = 'What percentage triggers approval?'
    start, end, method, score = align('trigger', source)
    assert source[start:end] == 'triggers'
    assert method == 'token_alignment' and score == 1


def test_offsets_are_rebuilt_and_auditable():
    item = frame()
    item['source_spans'][0].update(source_start=999, source_end=1000)
    corrections = []
    result = validate_interpretation(json.dumps(output(item)), QUESTION, corrections=corrections)
    for span in result.frames[0].source_spans:
        assert QUESTION[span.source_start:span.source_end] == span.source_span
    assert corrections
    action_correction = next(item for item in corrections if item['field'] == 'business_action')
    assert action_correction == {
        'frame': 0,
        'field': 'business_action',
        'code': 'aligned_source_span',
        'text': 'approve',
        'context_index': None,
        'normalised_value': 'approve',
        'source_span': 'approve',
        'source_start': QUESTION.index('approve'),
        'source_end': QUESTION.index('approve') + len('approve'),
        'alignment_method': 'exact',
        'alignment_score': 1.0,
    }


def test_protected_values_fail_complete_semantic_validation():
    question, item = permission()
    for changes in (
        {'numeric_values': ['25%']}, {'modality': 'must'},
        {'known_actor': 'sales directors'}, {'polarity': 'negative'},
    ):
        with pytest.raises(ValueError):
            validate_interpretation(
                json.dumps(output({**item, **changes}, question=question)), question,
            )
