"""Metric, leakage and budget checks; these establish software behaviour only."""
from copy import deepcopy

import pytest

from decidr.retrieval_benchmark import (
    bounded_context, digest, fill_budget, references, score_retrieval, set_metrics, validate_spec,
)


def example():
    catalog = {eid: {'evidence': {'source_id': sid, 'text': eid}} for eid, sid in
               [('a', 'phase2:s1'), ('b', 'phase2:s1'), ('c', 'phase2:s2')]}
    row = dict(group_id='g', evidence_id='a', source_id='phase2:s1', quote='a',
               passage_sha256=digest('a'), relevant=True, relationship='support',
               applicable=True, status='provisional', reviews=[])
    case = dict(case_id='q', group_id='g', family='f', split='familiar_development',
                target='prescribed_rule', wording='A claim is stated.')
    return catalog, dict(phase='phase2', purpose='development_only', cases=[case], judgements=[row])


def test_unknowns_do_not_become_irrelevant_and_one_hit_is_not_complete_recall():
    m = set_metrics({'a', 'b', 'u'}, {'a', 'c'}, {'b'})
    assert m['known_irrelevant_returned'] == 1
    assert m['unjudged_ids'] == ['u']
    assert m['precision'] is None and m['recall'] is None
    assert m['known_pool_recall'] == 0.5
    assert m['judged_precision'] == 0.5
    assert m['precision_bounds'] == [1 / 3, 2 / 3]


def test_document_precision_is_not_passage_precision_and_counterevidence_is_separate():
    catalog, spec = example()
    rows = spec['judgements'] + [{**spec['judgements'][0], 'evidence_id': 'b',
                                  'relationship': 'contradict', 'decisive_counterevidence': True,
                                  'exception': True}]
    m = score_retrieval(['a'], rows, catalog)
    assert m['document']['known_pool_recall'] == 1
    assert m['passage']['known_pool_recall'] == 0.5
    assert m['decisive_counterevidence']['recovered'] == 0
    assert m['exception']['missed_ids'] == ['b']
    negative = [{**rows[0], 'relevant': False}]
    assert score_retrieval(['a'], negative, catalog)['document']['unjudged_ids'] == ['phase2:s1']


def test_provisional_label_does_not_count_as_independent_reference():
    catalog, spec = example()
    report = references(['a'], spec['judgements'], catalog, {})
    assert report['independent']['passage']['unjudged_ids'] == ['a']
    assert report['independent']['passage']['precision'] is None
    assert report['provisional_diagnostic']['passage']['known_pool_recall'] == 1


@pytest.mark.parametrize('change', ['phase', 'family_split', 'group_split', 'quote', 'source', 'agent_review'])
def test_leakage_and_reference_bindings_are_rejected(change):
    catalog, spec = example()
    validate_spec(spec, catalog)
    if change == 'phase':
        spec['phase'] = 'phase3'
    elif change in {'family_split', 'group_split'}:
        case = {**spec['cases'][0], 'case_id': 'other', 'wording': 'Another wording is used.',
                'split': 'family_disjoint_development'}
        if change == 'family_split':
            case['group_id'] = 'different'
        spec['cases'].append(case)
    elif change == 'quote':
        spec['judgements'][0]['quote'] = 'invented quote'
    elif change == 'source':
        spec['judgements'][0]['source_id'] = 'phase2:wrong'
    else:
        spec['judgements'][0].update(status='independently_adjudicated', adjudicator='agent',
                                    rationale='Agent agreement', reviews=[
                                        dict(reviewer='agent-a', kind='agent', independent=True,
                                             completed_at='2026-09-10'),
                                        dict(reviewer='agent-b', kind='agent', independent=True,
                                             completed_at='2026-09-10')])
    with pytest.raises(ValueError):
        validate_spec(spec, catalog)


def test_complete_pool_flag_cannot_hide_unjudged_corpus():
    catalog, spec = example()
    review = dict(status='independently_adjudicated', adjudicator='human-c', rationale='Reviewed',
                  reviews=[dict(reviewer=r, kind='human', independent=True, completed_at='2026-09-10')
                           for r in ('a', 'b')])
    spec['judgements'][0].update(review)
    with pytest.raises(ValueError, match='all passages'):
        references(['a'], spec['judgements'], catalog,
                   {**review, 'corpus_relevance_complete': True})


def test_graph_backfill_and_context_share_the_candidate_budget(monkeypatch):
    import decidr.retrieval_benchmark as benchmark
    records = [{'evidence_id': eid, 'text': eid, 'source_id': 'phase2:s', 'locator': eid}
               for eid in ('a', 'b', 'c')]
    catalog = {r['evidence_id']: {'evidence': r, 'source': {}} for r in records}
    def attach(connection, selected):
        for record in selected:
            record['source_context'] = [records[2]] if record['evidence_id'] == 'a' else []
    monkeypatch.setattr(benchmark, '_attach_source_context', attach)
    monkeypatch.setattr(benchmark, 'evidence_catalog', lambda c: catalog)
    original = deepcopy(records)
    bounded = bounded_context(None, records[:2], 2)
    assert {r['evidence_id'] for r in bounded} == {'a', 'c'}
    assert records == original
    assert [r['evidence_id'] for r in fill_budget([records[0], records[2]], records, 3)] == ['a', 'c', 'b']
