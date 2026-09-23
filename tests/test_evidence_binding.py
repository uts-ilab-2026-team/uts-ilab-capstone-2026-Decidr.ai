"""Synthetic exact-span binding contracts; no live extractor or corpus evaluation."""

from dataclasses import replace

import pytest

from decidr.evidence_binding import (
    CandidateBinding, EvidencePacket, PendingEvidenceBinder, RetrievedEvidence,
    assess_query_bindings, claim_from_binding, grounded_bindings, retrieve_query_frame,
)
from decidr.models import ClaimOutcome, EvidenceMode, EvidenceRelationship
from test_query_frames import parsed, permission, output
from test_reasoning import _evidence


def packet():
    return EvidencePacket(items=[RetrievedEvidence(
        source_id='phase2:policy',evidence_unit_id='E-1',
        text='The Service Director has formally documented authority to approve onboarding timeline extensions.',
    )])


def candidate(**changes):
    return CandidateBinding(**{
        'requested_field':'authorised_role','extracted_value':'Service Director',
        'source_id':'phase2:policy','evidence_unit_id':'E-1',
        'exact_supporting_span':packet().items[0].text,'extraction_status':'candidate',**changes,
    })


class Binder:
    def __init__(self, values): self.values=values
    def bind(self, frame, evidence): return self.values


def test_grounded_binding_creates_real_claim_only_after_retrieval():
    frame=parsed().frames[0]
    assert frame.known_actor is None
    claim=claim_from_binding(frame,candidate(),packet())
    assert claim.subject=='Service Director'
    assert claim.predicate=='has formally documented authority to approve'
    assert claim.object=='onboarding timeline extensions'
    assert frame.known_actor is None


@pytest.mark.parametrize('changes',[
    {'extracted_value':'Invented Officer'}, {'exact_supporting_span':'Unfound quote'},
    {'source_id':'phase2:other'}, {'evidence_unit_id':'not-retrieved'}, {'requested_field':'threshold'},
])
def test_ungrounded_values_or_uncited_source_rejected(changes):
    with pytest.raises(ValueError):
        grounded_bindings(parsed().frames[0],packet(),Binder([candidate(**changes)]))


def test_binding_cannot_assign_verdict_or_confidence_or_truth_status():
    for key in ('verdict','confidence','credibility','relationship'):
        with pytest.raises(ValueError): candidate(**{key:'high'})
    q,f=permission();frame=parsed(output(f,question=q),q).frames[0]
    with pytest.raises(ValueError):
        grounded_bindings(frame,packet(),Binder([candidate(requested_field='truth_status')]))


def test_phase1_and_unbounded_evidence_rejected_before_component_call():
    with pytest.raises(ValueError):
        RetrievedEvidence(source_id='phase1:policy',evidence_unit_id='E1',text='Archived policy')
    forged=packet().model_copy(update={'items':[packet().items[0].model_copy(update={'source_id':'phase1:policy'})]})
    class MustNotRun:
        def bind(self,*args): pytest.fail('Phase 1 reached extraction')
    with pytest.raises(ValueError): grounded_bindings(parsed().frames[0],forged,MustNotRun())
    oversized=EvidencePacket(items=[RetrievedEvidence(source_id=f'phase2:P{i}',evidence_unit_id=f'E{i}',text='x'*8000) for i in range(6)])
    with pytest.raises(ValueError): grounded_bindings(parsed().frames[0],oversized,MustNotRun())


def test_no_binding_is_insufficient_and_pending_is_explicit():
    class Reviewer:
        def review(self,*args): pytest.fail('No claim exists before a grounded binding')
    for binder,status in ((Binder([]),'no_grounded_binding'),(PendingEvidenceBinder(),'extraction_pending')):
        r=assess_query_bindings(parsed().frames[0],packet(),binder,Reviewer(),employee_confirmed=True)[0]
        assert r.claim is None and r.reasoning.outcome==ClaimOutcome.INSUFFICIENT and r.status==status
    with pytest.raises(ValueError):
        assess_query_bindings(parsed().frames[0],packet(),Binder([]),Reviewer(),employee_confirmed=False)


def test_only_deterministic_reasoner_decides_contested_from_reviewed_incompatibility():
    p=packet()
    second=RetrievedEvidence(source_id='phase2:other',evidence_unit_id='E-2',
        text='Only the Operations Director has formally documented authority to approve onboarding timeline extensions.')
    p=EvidencePacket(items=[*p.items,second])
    values=[candidate(),candidate(source_id=second.source_id,evidence_unit_id=second.evidence_unit_id,
                                   extracted_value='Operations Director',exact_supporting_span=second.text)]
    class TrustedReviewer:
        def review(self,claim,evidence):
            # Synthetic reviewed incompatibility, not an LLM or different-values heuristic.
            return [replace(_evidence('1',EvidenceRelationship.SUPPORT,EvidenceMode.FORMAL_RULE),source_id='phase2:policy'),
                    replace(_evidence('2',EvidenceRelationship.CONTRADICT,EvidenceMode.FORMAL_RULE),source_id='phase2:other')]
    results=assess_query_bindings(parsed().frames[0],p,Binder(values),TrustedReviewer(),employee_confirmed=True)
    assert all(r.reasoning.outcome==ClaimOutcome.CONTESTED for r in results)
    assert all(r.claim.subject in {'Service Director','Operations Director'} for r in results)


def test_existing_hybrid_graph_retrieval_excludes_phase1_without_premature_atomic_claim(tmp_path):
    from decidr.database import connect,initialise_database
    from test_corpus_scope import _seed
    path=tmp_path/'ledger.sqlite3';initialise_database(path)
    q,f=permission();frame=parsed(output(f,question=q),q).frames[0]
    with connect(path) as connection:
        _seed(connection,'phase1');_seed(connection,'phase2')
        p=retrieve_query_frame(connection,frame,{'embedding_model':'unused'},employee_confirmed=True)
        assert p.items and all(i.source_id.startswith('phase2:') for i in p.items)
        assert connection.execute('SELECT COUNT(*) FROM claim_assessments').fetchone()[0]==0
