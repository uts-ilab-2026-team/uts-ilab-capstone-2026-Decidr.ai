"""Isolated scoring sensitivity, not interpretation accuracy or production policy."""

import argparse
from dataclasses import replace
from datetime import date, datetime, timezone
import hashlib
import inspect
import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

# Run from the repository; this downloaded runner is deliberately outside the app.
ROOT = Path.cwd()
if not (ROOT / 'decidr/assessment_adapter.py').is_file():
    raise SystemExit('Run this script from the Decidr-integration repository.')
sys.path.insert(0, str(ROOT))

from decidr.graph import CONFIG_PATH
from decidr.graph.config import GraphCredibilityConfig
from decidr.graph.credibility import GraphCredibilityFramework
import decidr.assessment_adapter as adapter
from decidr.assessment_response import serialize_facet_assessment
from decidr.interpretation_models import EvidenceInterpretation, InterpretationCitation
from decidr.corpus.models import Evidence, Source

VERSION = 'recorded-statement-sensitivity-v1'
BROAD_TARGETS = {
    'reported_practice': 'underlying_event',
    'limited_visibility': 'underlying_event',
    'instruction_vs_completion': 'underlying_event',
    'communication_vs_policy': 'formal_rule',
}


def digest(value):
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(',', ':')
    ).encode()).hexdigest()


class RecordedStatementCandidate(GraphCredibilityFramework):
    """Experimental override, available only in this standalone runner process."""

    def _evaluate_edge(self, edge, **kwargs):
        original = super()._evaluate_edge(edge, **kwargs)
        target = self.graph.nodes[edge.target].attributes.get('assessment_target')
        eligible = (
            target == 'recorded_statement'
            and edge.attributes.get('evidence_target') == 'recorded_statement'
            and bool(edge.attributes.get('target_basis', '').strip())
            and edge.relationship == 'OBSERVED'
            and original.applicable
            and original.stance in {'support', 'contradict'}
            and all(original.dimensions.get(key) == 1.0 for key in (
                'directness', 'specificity', 'evidence_completeness'
            ))
        )
        if not eligible:
            return original
        factor = max(original.dimensions['source_authority'], 0.1)
        score = original.materiality_score / factor
        return replace(
            original,
            materiality_score=score,
            material=score >= self.config.materiality_threshold,
            trace=tuple(
                'Baseline only (superseded in this experiment): ' + line
                if line.startswith('Materiality:') else line
                for line in original.trace
            ) + (
                f'EXPERIMENT {VERSION}: baseline {original.materiality_score:.6f} '
                f'/ outer authority {factor:.6f} = {score:.6f}. '
                'Authority remains a weighted dimension; other rules unchanged.',
            ),
        )


def prepare(case):
    pair = case['pair_id']
    if pair not in BROAD_TARGETS:
        raise ValueError(f'Undeclared development pair: {pair}')
    variant = case['case_id'].rsplit('--', 1)[-1]
    if variant not in {'narrow', 'broader'}:
        raise ValueError('Unexpected case variant')
    target = 'recorded_statement' if variant == 'narrow' else BROAD_TARGETS[pair]
    passages = [Evidence.model_validate(item) for item in case['evidence']]
    sources = [Source.model_validate(item) for item in case['sources']]
    if len(sources) != 1 or {p.source_id for p in passages} != {sources[0].source_id}:
        raise ValueError('This development runner expects one source per case')
    source = sources[0]
    source_class = {
        'interview': 'interview',
        'internal_communication': 'self_reported_communication',
    }[source.source_type]
    citations = tuple(InterpretationCitation(
        evidence_id=p.evidence_id, source_id=p.source_id, locator=p.locator,
        quotation=p.text, start=0, end=len(p.text),
    ) for p in passages)
    interpretation = EvidenceInterpretation(
        claim_text=case['claim_text'], facet=case['claim_text'], stance='support',
        mode='observed',
        rationale=(
            'Provisional supplied support for what the record says; no event verification.'
            if variant == 'narrow' else
            'Adversarial test-only support attempt: recorded statements must not establish '
            'this broader target. This is not a proposed semantic reference label.'
        ),
        citations=citations,
    )
    item = adapter.PreparedAttestation(
        interpretation=interpretation, source=source, origin_id=source.source_id,
        source_class=source_class, approval_key='unknown',
        scope_matches=True, temporal_matches=True, authority_verified=True,
        directness=1.0, specificity=1.0, completeness=1.0,
        judgement_basis=(
            'Experimental supplied assumptions only. Other admission flags and quality '
            'dimensions are held at their best case to isolate target and scoring effects. '
            'No authority or event dates were independently verified.'
        ),
        origin_basis='Source-level origin retained; cross-source independence unverified.',
        independence_verified=False, independence_basis='',
        evidence_target='recorded_statement',
        target_basis='Development declaration: this packet records testimony or communication.',
    )
    return target, passages, item


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--packet', type=Path, default=Path(
        'evaluation/credibility/observed-claim-scope-development-v1'))
    parser.add_argument('--as-of', type=date.fromisoformat, default=date(2026, 7, 31))
    parser.add_argument('--output-root', type=Path, default=Path('evaluation/credibility/runs'))
    args = parser.parse_args()
    originals = {name: (args.packet / name).read_bytes() for name in (
        'inputs.json', 'references.proposed.json', 'manifest.json')}
    inputs = json.loads(originals['inputs.json'])
    manifest = json.loads(originals['manifest.json'])
    if digest(inputs) != manifest['inputs_sha256']:
        raise ValueError('Packet input hash mismatch')
    expected_ids = {f'{pair}--{variant}' for pair in BROAD_TARGETS
                    for variant in ('narrow', 'broader')}
    if len(inputs) != 8 or {c['case_id'] for c in inputs} != expected_ids:
        raise ValueError('Expected the frozen eight-case development packet')
    for case in inputs:
        if digest({k: v for k, v in case.items() if k != 'input_sha256'}) != case['input_sha256']:
            raise ValueError(f"Case hash mismatch: {case['case_id']}")
    # References are archived with the run, not used as predictions or accuracy labels.
    config_bytes = CONFIG_PATH.read_bytes()
    config = GraphCredibilityConfig.load(CONFIG_PATH)
    code_paths = [Path(inspect.getfile(GraphCredibilityFramework)),
                  Path(inspect.getfile(adapter)), ROOT / 'decidr/assessment_targets.py',
                  Path(__file__).resolve()]
    hashes = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in code_paths}
    results = []
    print('EXPERIMENT ONLY — SUPPLIED TARGETS AND BEST-CASE QUALITY ASSUMPTIONS')
    for case in inputs:
        target, passages, item = prepare(case)
        kwargs = dict(claim_text=case['claim_text'], facet=case['claim_text'],
                      as_of=args.as_of, prepared=[item], evidence=passages,
                      config=config, assessment_target=target)
        baseline = adapter.assess_prepared_facet(**kwargs)
        # Context-managed override in this process only. No server or file is changed.
        with patch.object(adapter, 'GraphCredibilityFramework', RecordedStatementCandidate):
            candidate = adapter.assess_prepared_facet(**kwargs)
        if adapter.GraphCredibilityFramework is not GraphCredibilityFramework:
            raise AssertionError('Experimental override was not restored')
        for before, after in zip(baseline.inputs, candidate.inputs, strict=True):
            assert before == after  # Admission and original citation provenance unchanged.
        narrow = case['case_id'].endswith('--narrow')
        if not narrow:
            assert not candidate.assessment.evidence
            assert candidate.inputs[0].edge_id is None
        record = {
            'case_id': case['case_id'], 'input_sha256': case['input_sha256'],
            'baseline': serialize_facet_assessment(baseline),
            'candidate': serialize_facet_assessment(candidate),
        }
        results.append(record)
        print(f"\n{case['case_id']} | target={target}")
        for label, result in [('baseline', baseline), ('candidate', candidate)]:
            scores = [round(e.materiality_score, 4) for e in result.assessment.evidence
                      if e.materiality_score is not None]
            print(f'  {label}: {result.assessment.overall_outcome}; scores={scores}')
        if candidate.inputs[0].reasons:
            print('  Retained without edge:', '; '.join(candidate.inputs[0].reasons))
    assert all((args.packet / name).read_bytes() == raw for name, raw in originals.items())
    assert CONFIG_PATH.read_bytes() == config_bytes
    assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest() == h for p, h in hashes.items())
    try:
        revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True, stderr=subprocess.DEVNULL).strip()
    except subprocess.CalledProcessError:
        revision = 'unknown'
    output = args.output_root / (VERSION + '-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    output.mkdir(parents=True, exist_ok=False)
    for name, raw in originals.items():
        (output / name).write_bytes(raw)
    (output / 'configuration.json').write_bytes(config_bytes)
    (output / 'runner.py').write_bytes(Path(__file__).read_bytes())
    (output / 'results.json').write_text(json.dumps(results, ensure_ascii=False, indent=2) + '\n')
    (output / 'run.json').write_text(json.dumps({
        'experiment_version': VERSION, 'git_revision': revision,
        'as_of': args.as_of.isoformat(), 'code_sha256': hashes,
        'configuration_sha256': hashlib.sha256(config_bytes).hexdigest(),
        'results_sha256': digest(results), 'scoring_formula_promoted': False,
        'limitations': [
            'Target declarations, support attempts and quality assumptions are supplied.',
            'Broader cases are adversarial target checks, not interpretation predictions.',
            'Only recorded-statement scores are experimentally adjusted.',
            'No held-out evaluation, calibration, or accuracy claim.',
        ],
    }, indent=2) + '\n')
    print(f'\nSaved: {output}')
    print('PASS | Input hashes, citation provenance, target exclusions and override restoration')
    print('Production files and frozen packet unchanged; no database opened or model called.')
    print('Results are experimental, conditional on supplied judgements; no accuracy measured.')


if __name__ == '__main__':
    main()
