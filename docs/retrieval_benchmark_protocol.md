# Phase 2 retrieval and assessment benchmark

Primary acceptance criterion: generalisation to unseen Phase 3 claims. The present
benchmark is development evidence only. Neither passing tests nor matching the agent's
proposed labels establishes readiness.

Read the [completed findings and change proposals](../reports/retrieval-generalisation-phase2/findings.md)
for measured results, preserved run versions and the independent-review handoff.

The [hardcoding audit](retrieval_hardcoding_audit.md) preceded implementation. The new
runner is `decidr/retrieval_benchmark.py`; it does not change production retrieval,
classification, business rules or verdicts.

## Inputs and independence

`reports/retrieval-generalisation-phase2/prepare.py` defines nine underlying claim groups,
each with two wordings, and 62 explicit passage judgements. The judgements were written
from Phase 2 source passages before running this comparison. They include support,
contradiction, qualification, context, negative relevance examples, decisive counterevidence
and exceptions. Each has an evidence ID, source ID, exact quotation, text hash, rationale,
applicability judgement (including unknown) and review status. Source types include policies,
procedures, interviews, meetings, communications, task records and audit logs, as well as
organisational information. No relationship is generated from retrieval rank.

No independent references were available in the active ledger. The supplied judgements
remain **provisional** and the relevant sets **incomplete**. A document or passage that is
not in these sets is not thereby irrelevant. Disagreements with these labels are diagnostic
review candidates, not confirmed model errors. No final verdict gold labels were invented.

The runner copies only sources and evidence into a temporary database. It does not load
claims, historical automatic responses, portfolio rows, reviews or adjudications from the
working ledger. It rejects non-Phase-2 sources and non-development input declarations.
Approach B's portfolio-backed parser is not invoked: the audit identified its missing split
filter. No Phase 3 file or held-out portfolio contents are required.

## Grouping and familiarity

The underlying-claim `group_id` is the unit of paraphrase grouping. All wordings of a claim
must share a target, family and development split; families cannot cross splits. The familiar
stratum contains discount, onboarding, travel and ticket closure. The separate family stratum
contains data export, probation, feature intake, billing incident records and collections.

These are **family-disjoint development stress cases**, not independently certified unseen
families. The repository already contains broad corpus knowledge. A source-near wording
is not necessarily a familiar exact development example. Newly proposed paraphrases are
also not a guarantee of novel semantics; their equivalence needs independent review. They
become development-exposed on this run. No method was tuned against either stratum here.

For later tuning, assign entire scenario families (and all near-duplicate claims) to one
fold before inspecting scores. A reviewer must check semantic duplicate groupings; lexical
deduplication alone cannot catch paraphrase leakage. Report the family as the unit of
uncertainty; do not treat correlated paraphrases as independent sample size.

## Matched retrieval comparison

Run the same cases on the same evidence-only ledger at budgets 10, 20 and 50:

* Raw-text FTS5 BM25, using the employee wording unchanged.
* Structured-field FTS5 BM25, using the existing intake output. Its behaviour is contingent
  on successful interpretation; pending intake is not silently replaced by oracle fields.
* Employee provenance expansion from the first 60% of the lexical budget.
* Approach B's depth-one metadata expansion from the same lexical seeds, capped to budget.
* Semantic cosine ranking and RRF hybrid when the actual configured local model exists.
  Unavailable components are reported as unavailable, never relabelled lexical fallbacks.

Graph methods preserve seed order, append their existing traversal results, then backfill
unused slots from the lexical ranking. Unique evidence IDs count once. The seed allocation
is fixed before scoring and is an experimental budget choice, not a selected optimum.
These are retrieval-component ablations with a shared downstream assessor, not an accuracy
claim for Approach A's human-dependent assessment or Approach B's portfolio parser.

Two stages are scored separately: ranked candidates and the final exposed packet. The
common packet builder admits a candidate followed by its existing same-source header and
exception context, all charged to the final budget. Context references are pruned to admitted
passages. This exposes any relevant ranked evidence displaced by context. The entire text of
each admitted passage is used; these are passage budgets, not equal token budgets. All methods
have the same corpus metadata and provenance graph. Internal search/graph enumeration costs
are not equal compute budgets and no latency superiority is claimed.

The unmodified native employee pipeline runs separately and retains its full automatic
snapshot. Native extra context is counted explicitly. It is not mixed into the matched-budget
comparison, because the existing application attaches passages beyond its advertised limit.

## Metrics and unknown evidence

Document and passage precision and recall are separate. A document is known relevant if it
contains a known relevant passage. It is known irrelevant only if all its passages are judged
irrelevant. One irrelevant passage never makes an entire document irrelevant.

For each stage and each granularity, report returned count, known relevant found/missed,
known irrelevant returned, all unjudged IDs, judged precision, and precision bounds:
`[known relevant / returned, (known relevant + unjudged) / returned]`.
Full precision is withheld while returned candidates are unjudged. Empty denominators are
undefined, not invented perfect scores. Full corpus recall requires a complete independent
corpus relevance review; the runner requires an independent judgement for every eligible
passage plus a completion declaration. Otherwise it reports **known-pool recovery**, which
must never be called complete recall.

Independent and provisional results are different namespaces. Agent-proposed evidence is
unjudged in the independent namespace, even when both agent and classifier agree. Independent
references require two distinct declared independent human reviewers, completion dates,
adjudicator and rationale. These provenance declarations need genuine review outside the
runner; local names are not identity authentication. No current result meets that gate.

Report supporting, contradicting, qualifying and contextual recovery separately. Report
applicable decisive counterevidence and exception recovery, including exact missed IDs.
Relevance is independent of applicability: an obsolete policy, draft or cross-target practice
can be important context even when it cannot establish the current claim.

Graph deltas include added and displaced passages, proposed relevant gains/losses, unjudged
additions and paired automatic verdict changes. A changed verdict is not an improved verdict.
`assessment_improved` stays null without an independent claim-level reference. Human-grounded
oracle evidence/classification interventions may later isolate causal error sources, but
must be labelled diagnostic and cannot replace end-to-end evaluation.

## Assessment and failure attribution

Automatic snapshots preserve intake, exact original wording, source-linked support,
contradiction, qualifications, context, exclusions, unclassified candidates, gaps, limitations,
next steps, source roles where established, per-target findings and classifier notes. They
are saved before review and are not recomputed by the scoring functions.

The existing intake, automatic classifier and complete employee reasoner run unchanged in
the scratch ledger. Explicit benchmark target selection is analogous to the employee choosing
an assessment target; it does not insert a source answer into claim fields. Other intake
fields are never supplied from reference labels. Pending meaning remains pending.

Keep these stages distinct when reviewing failures:

| Stage | Evidence required to establish a failure |
|---|---|
| Retrieval | Independently relevant passage absent from ranked or exposed packet; distinguish the two. |
| Interpretation | Independent comparison of original wording with actor, event, polarity, quantifier, scope, clock and target in the parsed claim. Parsing success alone is insufficient. |
| Relationship | Retrieved passage judged support/contradict/qualify/context differently from independent reviewers; record unclassified separately. |
| Applicability | Relationship understood, but population, target, time, authority or condition gate is wrong. Keep relevance even when applicability is false. |
| Final verdict | Independent assessment of the complete applicable evidence set differs from the saved automatic result. Correct outcomes can mask upstream errors. |

The machine report records retrieval misses, provisional relationship/applicability
disagreements and intake status. Final-verdict correctness remains null until reviewed.
Next actions must cite the relevant evidence gap or comparison. Source ownership alone is
not decision authority; do not assign business roles or thresholds without explicit sources.

## Independent review packet

Give each reviewer `blind-review.json` and `corpus.json`, with this protocol. Do not give
them `benchmark.json`, `results.json` or automatic snapshots until their independent pass is
complete. The blind packet removes rankings, proposed labels and predictions, mixes pooled
candidate IDs deterministically, and links the full corpus for additional evidence discovery.
The shared query variants reveal the claim group intentionally, not the method that retrieved
a passage. Reviewers must include additional sources outside the pool.

Each reviewer should record, per group and passage: relevance; relationship; target; scope,
time and condition applicability; decisive counterevidence; exception; exact quote; rationale;
and confidence in the judgement. Also record the intended interpretation and final verdict
with decisive source IDs, qualifications, gaps and justified next action. Do not force a
single relation for an internally mixed passage without explaining the aggregation.

Adjudicate disagreements separately, preserving both originals and unresolved disagreement.
An incomplete packet can be reviewed without declaring the entire corpus complete. A second
version of the benchmark may incorporate independently adjudicated rows with provenance;
keep all provisional originals. Claim-level final-verdict scoring needs a separate independent
reference and must not use the production reasoner to manufacture its expected outcomes.

## Freeze, execution and Phase 3 boundary

Example (use a new output directory on each invocation):

```sh
.venv/bin/python reports/retrieval-generalisation-phase2/prepare.py
.venv/bin/python -m decidr.retrieval_benchmark \
  --spec reports/retrieval-generalisation-phase2/proposed-benchmark.json \
  --output reports/retrieval-generalisation-phase2/run-v1
```

Preparation also refuses to overwrite its original proposed dataset. The freeze records
all runtime/application/configuration files, dependency lockfile and installed versions,
benchmark/corpus hashes, source snapshot date, candidate budgets and seed fraction. It
archives the exact pipeline files before evaluation, checks code hashes again on completion,
and hashes all outputs. A run lacking `completion.json` is incomplete or invalid.

This is a **baseline measurement freeze**, not a selected Phase 3-ready pipeline. The runner
deliberately has no Phase 3 evaluation mode. Complete independent Phase 2 review and agree
acceptance thresholds before selecting a pipeline. Then freeze ingestion, extraction,
models and model-file hashes, prompts, interpretation, retrieval and token/candidate budgets,
graph traversal, classification, applicability, verdict rules and explanation generation.
Resolve any nondeterminism and retain raw model outputs.

A separate validation custodian should hold Phase 3 claim and label artifacts. Only after
selection/freeze should that custodian run the pipeline on validation claims; save automatic
outputs before joining labels or permitting optional human review. Record the first-pass
results separately. Every later code, model, prompt, corpus or threshold change needs a new
version, reason, previous results, changed-file hashes, and a labelled reevaluation. Once a
validation claim influences a fix it is development-exposed; rerunning it is no longer an
unseen-readiness test. Use a fresh untouched validation set for a new generalisation claim.

### Additional execution records

The first run used the existing ledger and no semantic model. A subsequent isolated
semantic run captured the exact model revision and SHA-256 hashes for the inference files.
The configured model is `sentence-transformers/all-MiniLM-L6-v2`; its downloaded cache is
under `data/processed/retrieval-benchmark-model-cache`. To use that existing cache without
network access:

```sh
uv run --frozen --isolated --extra semantic python -m decidr.retrieval_benchmark \
  --spec reports/retrieval-generalisation-phase2/proposed-benchmark.json \
  --output reports/retrieval-generalisation-phase2/new-run-name \
  --model-cache data/processed/retrieval-benchmark-model-cache
```

`--model-cache` enables offline loading; it does not install packages or download a model.
The local comparison ran on MPS; hardware and model files are recorded. Small cross-device
ranking differences remain possible. Repeated model-stability trials and a token-budget
comparison were not performed.

Re-ingestion checks also found stale metadata in the existing ledger despite identical
passage IDs/text. The freshly ingested snapshot was therefore evaluated separately, keeping
claims and proposed labels fixed. See `reports/retrieval-generalisation-phase2/` for versioned
runs and `ingestion-reproducibility.json`. The working ledger was not rebuilt. A corpus
checksum based only on raw source content cannot detect this metadata drift; include the
full ledger revision and source metadata in a selected-pipeline freeze.
