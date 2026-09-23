# Experimental structured statement extraction

**Status: development comparison complete (62/62); candidate rejected for promotion and disabled.**
Production remains `bounded-evidence-5`; there is no production import, configuration switch,
UI replacement or working-ledger write for this candidate. Automatic assessment still
precedes optional human review. Existing source links, explanations, recommendations and
immutable assessment history are untouched.

## Corrected metadata follow-up

The results below are the **original frozen research history**. The separately versioned
[metadata correction](source_metadata_correction.md) fixes document attribution and evaluation
inputs without rerunning either model. Applicability agreement becomes 62/62 (previously 56/62)
against unchanged provisional labels; direct-model downstream matches become 55/62 (previously
54/62), solely from excluding expired POL-02 evidence. Relationship and component outputs do
not improve. The [reviewer packet](../reports/metadata-correction-development-v1/reviewer-packet.html)
contains pending label disputes and exact passages. Both alternatives remain disabled.
Ingestion/applicability code has changed; the classifier and original experimental runtime,
matrices, responses, scores, manifests and snapshot artifacts are preserved.

## Representation and validation

`decidr/experimental_extraction.py` defines separately cited actor, action, object, authority
status, target, negation, quantifier, scope, threshold, individual conditions and exceptions,
start event, completion event, effective start/end and lifecycle. Non-null components require
an exact quotation and addressed source unit. Unknown scalar values remain null; empty lists
mean unspecified, not proof that conditions or exceptions do not exist.

Claim components may cite only submitted wording or the explicitly requested target. Evidence
components may cite only the frozen passage, same-source context or separately labelled
ingestion metadata. Exact offsets are recorded for every accepted quotation. Invalid origins,
spans, typed values or uncited values are quarantined as unknown and retained in a diagnostic.
A citation-valid but semantically wrong value can survive: provenance validation never certifies
meaning. `epistemic_status=model_proposed_sourced_assertions`,
`semantic_validation=not_independently_adjudicated`, and `established_facts=[]` are explicit.

The joint-request pilot and raw failures are preserved under
`reports/structured-extraction-development/responses`. It exposed source-to-claim leakage.
The main candidate uses physically separate model requests (`run_separated.py`): claim
extraction sees only CLAIM and TARGET. Source extraction sees source units plus an uncited
focus consisting of the proposed action, object and target. Focus cannot serve as evidence.
Identical source/focus requests reuse content-addressed outputs. The source pass selects at
most one assertion per unit and explicitly reports that interpretation coverage is incomplete.
No normalisation or comparison is dispatched by case ID, policy ID or expected label.

## Deterministic checks and their limits

Comparable typed boundaries retain inclusive/exclusive operators, numeric value, unit and
basis. The comparator supports equality and limited point membership, and does not treat
unequal upper bounds as universal contradiction. Unknown denominators remain incomparable.
Source and claim target are compared separately. Explicit unassignment can contradict an
assignment assertion; missing documentation cannot prove denial. Different population scopes,
conditions or start/completion events are retained as uncertainty/qualification rather than
silently unified. Claim conditions absent from the source do not become established facts.

Known ingestion dates gate applicability. Draft status, a source created after the assessment
and intervals outside the relevant date cannot establish an effective rule. Missing effective
starts remain unknown. Extracted dates cannot override conflicting metadata or become effective
dates merely because the model proposes them. All semantic identity checks remain conditional
on the unverified extracted representation; deterministic code does not make that premise true.

## Separate evaluations

The frozen 46-case development matrix from `assessment_quality_and_presentation.md` is retained
byte-for-byte. A new experiment matrix adds 16 fresh development paraphrases, with provisional
component annotations written before inference. No held-out claims, portfolio labels or
independent human judgements are supplied to the extractor. Both previous baselines are
compared: unchanged bounded classification and the original direct-verdict Qwen prompt. Frozen
direct-model responses are reused; the identical prompt/model/settings are run on fresh cases.

- Extraction: raw and validated component matches, known-component omissions, unknowns wrongly
  filled, citation rejection and per-field results. Partial labels and normalisation disputes
  are marked for independent adjudication. The baselines expose no comparable component schema.
- Relationships: coverage and exact provisional matches, with serious support/contradiction
  reversals and false decisive findings separated from contextual/qualifying disagreements
  and abstentions.
- Downstream: designated-passage diagnostics through the existing `assess_claim` reasoner,
  with the same fixed materiality and metadata-date gates for every method. Expected outcomes
  are derived from the provisional relationship/date labels, not independent verdict labels.
  Full-corpus or full-packet deployment performance is not claimed.

The initial pilot is not pooled with the separated candidate. Prompt/schema/model versions,
request hashes, raw model outputs, citation failures, experimental graph overlays and all
component comparisons are saved. The [complete case report](../reports/structured-extraction-development/separated/comparison.html)
and [machine-readable scores](../reports/structured-extraction-development/separated/scores.json)
contain all 62 cases. The [manifest](../reports/structured-extraction-development/separated/manifest.json)
freezes the prompts, schema, model digest and runtime/matrix hashes. The earlier joint pilot
was stopped after 11 saved cases and is not pooled with this comparison.

## Completed comparative results

Counts below are **classified / matching provisional relationship label**, with coverage in
parentheses. Abstentions are not counted as matches. These are purposive development examples,
not independent accuracy estimates.

| Method | Frozen 46 | Fresh 16 | Total 62 |
|---|---:|---:|---:|
| Unchanged bounded classifier | 11 / 9 (23.9%) | 3 / 0 (18.8%) | 14 / 9 (22.6%) |
| Direct-verdict local model | 41 / 29 (89.1%) | 15 / 11 (93.8%) | 56 / 40 (90.3%) |
| Structured candidate with citation gate | 2 / 0 (4.3%) | 1 / 0 (6.3%) | 3 / 0 (4.8%) |

The direct model has three serious support/contradiction reversals and ten false-decisive
relationships (seven frozen, three fresh), plus three missed decisive relationships and six
abstentions. These severity assignments depend on the provisional relationship labels and
require adjudication. The bounded classifier has three contextual/qualifying disagreements,
two missed decisive relationships and 48 abstentions. The candidate has three missed decisive
relationships and 59 abstentions; no decisive candidate finding was produced. Absence of a
serious decisive error at this coverage is not evidence of useful or reliable assessment.

| Component measure | Frozen 46 | Fresh 16 |
|---|---:|---:|
| Partially annotated components | 900 | 312 |
| Raw strict normalisation matches | 674 | 213 |
| Raw known-component matches / known labels | 419 / 639 | 122 / 221 |
| Raw known-component omissions | 92 | 38 |
| Raw annotated unknowns filled | 6 / 261 | 0 / 91 |
| After validation: known-component matches | 290 / 639 | 88 / 221 |
| After validation: known-component omissions | 255 | 92 |
| After validation: non-null label disagreements | 94 | 41 |
| Cases with rejected components | 44 / 46 | 15 / 16 |
| Rejected components | 258 | 82 |

All 62 responses parsed into the statement schema, but 59 had component-level citation, origin
or typed-value failures. Validation removed the six filled annotated unknowns; it did not
establish semantic correctness. The 135 surviving non-null label disagreements include both
substantive mistakes and normalisation disputes. Seven metadata-derived annotations have
explicit adjudication caveats below. These counts are not 135 independently confirmed semantic
errors. Field-level and claim/source-separated results are retained in the score file.

The deliberately unguarded diagnostic classified 36/62 and matched only 3/62 provisional
relationships, with 30 missed decisive relationships and three other scope/context disagreements.
Bypassing citations therefore does not establish a viable recovery path. It is diagnostic only.

| Isolated downstream measure | Bounded | Direct model | Structured |
|---|---:|---:|---:|
| Verdict-label matches, frozen / fresh | 32/46 · 9/16 | 40/46 · 14/16 | 26/46 · 9/16 |
| Expected decisive verdicts correctly produced | 6/27 | 26/27 | 0/27 |
| Wrong decisive verdicts | 0 | 7 | 0 |
| Serious relationship errors masked by matching verdict | 0 | 6 | 0 |

The candidate returns `Insufficient evidence` for all 62 designated-passage diagnostics: its
35 matching verdicts are entirely unresolved cases. This is not successful assessment of the
27 cases provisionally expected to be decisive. No new coverage verdict category is introduced.
These are fixed-assumption reasoner diagnostics, not deployed pipeline or full-packet scores.

The shared metadata-only date gate and the candidate interval check both match 41/46 frozen
and 15/16 fresh date labels. The direct model's own date responses match 28/46 and 11/16 after
its original response validation. Candidate interval checks do not promote model-proposed dates
into established dates. Six shared-gate mismatches are explained by the frozen metadata issues
below. The shared gate was held constant across methods for the downstream comparison.

**Decision:** keep both alternatives disabled. The structured architecture as implemented does
not improve either coverage or relationship correctness. The current bounded classifier also
remains unreliable for these distinctions; this experiment does not vindicate it. The current next
research step is independent adjudication using the corrected metadata dataset and reviewer
packet. Event identities, source-only constraints and multiple assertions remain documented
research failures; no broad extraction redesign or another model experiment is launched or
authorised by this follow-up. Any later experiment requires a separate version and evaluation.

## Observed failure mechanisms

These are development observations, not independently adjudicated error labels. The raw
responses and accepted/rejected components are available in the case report.

- [Ticket completion event](../reports/structured-extraction-development/separated/comparison.html#source-frozen-10):
  the source says “Support Lead confirms resolution with the customer and closes the ticket.”
  The extractor attaches the sales event `closed_won` to an exact quotation from this passage.
  The same response merges confirmation and closure into an action and leaves the object
  unknown. Exact span validation accepts the wrong event meaning.
- [Formal versus practice target](../reports/structured-extraction-development/separated/comparison.html#source-frozen-13):
  a prescribed-rule assessment is extracted as `actual_practice`, and the procedure's source
  assertion is also labelled practice. Physical request separation does not ensure that the
  selected target or source mode is interpreted correctly.
- [Authority table selection](../reports/structured-extraction-development/separated/comparison.html#source-frozen-06):
  same-source context includes several decisions involving the same role. The source pass can
  select escalation-process changes rather than the requested onboarding deviation. A valid
  citation to another row does not make that row relevant.
- [Boundary and condition comparison](../reports/structured-extraction-development/separated/comparison.html#source-frozen-24):
  the candidate returns a qualification for an inclusive-boundary claim provisionally labelled
  support. Differences in condition encoding can determine the result before the numeric check.
  The claim's percentage basis remains unknown; the source explicitly says list price.
- [Frozen temporal metadata](../reports/structured-extraction-development/separated/comparison.html#source-frozen-10)
  calls the approved support procedure a draft, although its quoted approval statement describes
  the other document as the unapproved revision. Separately, the
  [old discount policy](../reports/structured-extraction-development/separated/comparison.html#source-frozen-45)
  has no ingested end date, while its frozen header explicitly gives a superseded date. The
  experiment's metadata-only date gate inherits these errors. It does not reconcile all source
  headers or successor intervals. The frozen metadata is preserved, and date-label disagreement
  is reported separately; deterministic comparison cannot certify incorrect input metadata. The
  [adjudication notes](../reports/structured-extraction-development/adjudication-notes.json)
  also flag seven affected component annotations that inherited this metadata. Strict-match
  totals retain the frozen labels and must not be read as semantic gold.
- Some components use the string `"null"`, omit citations, quote altered Markdown, or supply a
  source identifier where the request requires a unit key. These are contract failures,
  distinct from missing evidence. One such failure blocks the entire assertion comparison,
  including when the rejected component is not material to that comparison.

The deterministic comparator is deliberately small and also incomplete: free-form action/object
normalisations can turn paraphrases into `not_applicable`; source-only constraints are not fully
composed; exception and condition sets are not a general logical entailment calculus. An
unguarded offline diagnostic bypasses the citation gate to expose these semantic failures hidden
by abstention. It is not an additional deployable baseline and is not a proposed way to recover
coverage. Future work needs a separately versioned representation/comparator evaluation, not
acceptance of invalid citations or isolated claim-specific wording patches.

## Knowledge graph connection and retrieval comparison

`assertion_graph` creates a detached NetworkX overlay sharing frozen source/evidence IDs.
It adds a reified `sourced_assertion` node rather than a direct `role → authorised_for` fact.
`ASSERTED_IN` retains the assessment target; `COMPONENT_CITED_FROM` retains component name,
quote, offsets and provenance status. The existing evidence → source edge is preserved.
The report overlay separately records the immutable requested target and model-proposed assertion
target, and adds an `ASSESSED_AGAINST` edge carrying the provisional evidence relationship and
explanation. Unknowns stay in the assertion payload. No actor identity merge, authority inference, credibility
boost or retrieval expansion is licensed by these model-proposed edges.

Production integration, if justified later, would attach this overlay to the same immutable
assessment snapshot and retain its source-inspection identifiers. No schema migration is needed
for the experiment. Standalone experiment graphs link to frozen excerpts in their HTML report;
they do not invent live run IDs. Graph display does not itself improve retrieval.

The separate [graph comparison](../reports/structured-extraction-development/graph-comparison.json)
measures lexical top-20/30/50, employee provenance expansion 20→30 and production 50→50,
and the legacy Research/admin depth-one expander both capped at 30 and uncapped. All use
the same queries, ledger and evidence IDs. Designated-passage recovery is saturated at 62/62
for lexical top-20, so no expansion recovery gain is demonstrated. The employee 20→30 variant
adds 74 unjudged candidate occurrences; the legacy expander adds 38. Production 50→50 adds
none. These are candidate occurrences across queries, not distinct documents, and unjudged
additions are not labelled irrelevant. Complete-pool recall, precision/F1, reviewer effort,
downstream benefit and learned assertion-edge retrieval remain unmeasured.

## Reproduction

For the current correction checkpoint, use the offline
[metadata replay command](../reports/metadata-correction-development-v1/README.md).
The commands below describe the historical model experiment; preserve its completed artifacts
and use a separate version if another experiment is later authorised.

Run `.venv/bin/python reports/structured-extraction-development/run_separated.py` with the
existing local Qwen3.5 model available through Ollama. It resumes only identical manifest/
request inputs and uses a content-addressed call cache. Preserve the saved outputs when
starting a new version; do not tune against held-out examples.

Run `score.py --separated` to score the main candidate, and `graph_comparison.py` to reproduce
the retrieval ablation in a temporary development ledger. Run `pytest` separately for workflow
checks. [Known limitations](known_limitations.md), [current guidance](claim_first.md) and the
[documentation inventory](documentation_inventory.md) distinguish research records from
current operating instructions.

## Workflow verification and preservation

Workflow verification is separate from the semantic results: **402 tests passed**. Ruff and
`git diff --check` pass. The [integrity audit](../reports/structured-extraction-development/preservation-check.json)
confirms that all 192 protected original production/configuration/data/framework/earlier-report
files retain their original hashes, all 13 archived guidance copies match their originals, and
no production module imports the candidate. The matrix and runtime still match the main run's
frozen manifest. The report's local links and graph source-inspection links are checked.

The documentation inventory separates current guidance, unpromoted experiments, archived
instructions and preserved research/submitted records. Existing uncommitted work, immutable
assessment history and held-out evaluation data are preserved. Nothing was enabled, committed
or pushed. Live browser visual verification is not claimed.
