# Claim-first Decidr prototype

The employee assessment sequence has been updated: a system verdict now precedes
optional human evidence review. See [Automatic employee assessments](automatic_claim_assessment.md)
for the current classifier, snapshot provenance, pending-claim recovery and limitations.
The human-review prerequisite described below documents the earlier workflow.

## Client direction and implementation decisions

The client priorities supplied for 8 September 2026 are claims first; inspectable evidence
and relationships; separate verdict and confidence; contradictions, applicable gaps and
information that would settle them; repeated-origin adjustment; current and explicitly
dated knowledge; sensitivity; an employee interface; and management knowledge risks.
Comprehensive transaction auditing is outside scope. Phase 3 reference claims are future
evaluation material, never runtime evidence or development labels.

Our implementation choices are Streamlit navigation, the existing SQLite ledger and FTS5,
optional already-local embeddings, bounded reciprocal-rank fusion and explicit provenance
graph expansion, conservative language patterns, and completed human evidence review
before deterministic assessment. These are prototype design choices, not client assertions
about extraction accuracy or formal selection of Approach A or B. Meeting examples and
counts are development leads; this implementation does not encode organisational thresholds,
authorised roles, transaction IDs or portfolio membership as answer branches.

## Start and use

From the repository root:

```sh
uv run streamlit run app/Home.py
```

The existing local Phase 2 ledger is reused. To build a ledger on another machine, configure
`DECIDR_PHASE2_DATA_DIR` in `.env`, then run `uv run python -m decidr.dataset`.
Read its side effects first: it reads raw inputs, can archive/replace a changed local ledger,
and writes ingestion registers under `reports/ingestion`. Unchanged ingestion preserves
reviews. For isolated validation use explicit `--database /tmp/...sqlite3 --output /tmp/...`.
No Phase 1 or Phase 3 evidence is eligible for employee retrieval.

Employee navigation:

1. **Assess a Claim**: enter a declarative statement and click **Assess claim**. Submission
   confirms its wording; there is no routine subject/predicate/object confirmation form.
2. **Claim Register**: return to entered claims and explicitly reviewed reusable claims.
   Reuse requires exact original wording, including case, punctuation and protected values.
   The previous assessment's scope, date and review provenance remain visible; reuse does
   not silently refresh an old result.
3. **Knowledge Risks**: inspect evidence-linked findings from each claim's latest completed
   assessment. Counts distinguish registered claims, assessed claims and pending claims;
   open review packets are counted separately. Categories can overlap. Findings are not
   confirmed breaches or population estimates.
4. **Evidence Explorer**: search and inspect complete excerpts, locators, dates, source
   metadata and bounded graph neighbourhoods without creating a claim or an assessment.

**Research / admin → Claim evidence review** completes application reviews. Existing study
setup, independent blind review, Approach A baseline, Approach B experiments, comparison,
audit and evaluation gates remain separately available. Reviewer names are local audit
identifiers, not authentication. This is not a multiuser security boundary.

## Intake contract and limits

`decidr/claim_intake.py` uses language patterns only. It never consults a portfolio or model.
The register stores the exact original submission, verbatim component spans, protected value
spans, shallow structured meaning, target, dates, clarification history and transformation
provenance. The schema's object contains the complete action complement and qualifiers;
it is deliberately not a claim of general actor/action/object extraction accuracy.

Supported input has an explicit subject, recognised modal/copular/recording/requirement
predicate and a nonempty complement. Unfamiliar actors, objects and processes are accepted.
Explicit modal requirements indicate prescribed rules; explicit practice or recording
language indicates the corresponding knowledge target. Ambiguous targets get one short
plain-language question. Dates in simple `on YYYY-MM-DD` / `as of YYYY-MM-DD` or
`from YYYY-MM-DD to YYYY-MM-DD` scopes can be represented. Ambiguous date roles, deadlines,
relative dates, other formats and incomplete conditional clauses remain pending.

The complete text is retained even where fine-grained linguistic extraction is unsupported.
Modal negation is kept distinct from a positive action with a `without ...` condition.
Quantities, units, comparisons, exclusions and conditions are never replaced with values
found in policy evidence. ISO dates appearing as recorded values are not silently treated
as assessment dates.

Explicit sentences and semicolons make component boundaries visible. An `and` boundary is
split only when both sides have independently stated subjects and recognised predicates
and no shared condition is being distributed. Noun lists are not split. Ambiguous joined
actions remain pending. Abbreviations, complex coordination, pronoun resolution, nested
reported speech, tense/aspect and arbitrary finite verbs are not reliably understood.
Human meaning review is mandatory at review completion, even for accepted bounded intake.

A target clarification is merged without replacing the proposition. Other clarifications
are appended for manual interpretation review. The admin fallback quotes subject,
predicate and complement from the original/clarification context and records a reviewer
justification; it never silently rewrites the original statement. If a reviewer cannot
resolve a compound, submit its fully stated components separately, retaining the original
pending entry as provenance. A parser failure receives **Awaiting clarification or
interpretation review**, never an evidence verdict.

## Review and assessment state machine

`employee_claims` extends the existing `claims` register without importing study items.
Application categories are `employee_entered` and `reviewed_reusable`; experimental and
held-out items remain in the research register, outside application enumeration or reuse.

`awaiting_clarification → awaiting_evidence_review → completed_assessment`

Starting a review freezes the exact claim, as-of date, retrieval method/status, candidate
packet, eligible source graph, corpus fingerprint and ledger revision. By default, lexical
and optional semantic rankings each return at most 20 results, fused with `k=60`. Explicit
source-origin/version expansion can add candidates up to 30. A reviewer can add eligible
items found in Explorer, up to a total of 50. Similarity and proximity never assign a
support/contradiction relationship. Semantic failures leave lexical candidates intact and
are displayed as lexical execution with an unavailable semantic component.

Review every candidate, including irrelevant candidates, against knowledge target, scope,
conditions and time. Set the relationship, evidence mode, seven credibility dimensions and
justifications. Default unchecked applicability boxes do not attest relevance. Proposals
remain untrusted. Completed human judgements use the existing `claim_evidence_links` and
`credibility_assessments` ledger with a unique application review namespace. Additional
notes store grounded source origins, gaps, settlement requests, documented role quotes and
risk rationales. Application completion does not manufacture a blind study judgement or
write formal evaluation records.

A completion receipt requires every candidate to have a completed human review, explicit
meaning attestation and a coverage rationale. An empty packet still requires explicit
completion and a request for evidence that would settle the claim. Unresolved completed
assessments require settlement information. An empty reviewed relationship set is never
used as evidence of corpus-wide absence. Pending work has no verdict or confidence metric.

Completed snapshots and their review receipts are immutable through the application API.
Further reviews create new packets. If evidence or source metadata changes while a review
is pending, it must restart. Completed snapshots remain reproducible and display their
historical as-of date and corpus fingerprint.

## Credibility, provenance and time

The shared deterministic reasoner retains the four established outcomes: Supported,
Contradicted, Contested and Insufficient evidence. Confidence is separately qualitative.
The baseline materiality threshold is 0.5 with equal dimension weights; these are transparent
reasoning assumptions, not calibrated probabilities. Source age, tenure and seniority do
not determine authority or factual correctness.

Each source's units count as one origin. Explicit derived-source chains, ingestion duplicate
groups and quoted reviewer-confirmed shared origins form transitive groups. Intermediate
source nodes remain in the graph and review snapshot. Repetition within the same relationship
is counted once; conflicting relationships within one origin remain visible and cannot
be discarded by choosing the first excerpt. Confidence counts distinct decisive origin
groups. Dependence between remaining groups is explicitly unknown, not proved independence.
Near-duplicate similarity alone does not merge origins.

For this ledger the default as-of convention is the latest creation date among eligible
sources: **2026-07-20**. The interface and every result expose it. It is not a claim that the
snapshot is exhaustive. Reviewers can choose another explicit as-of date. Explicit claim
periods govern rule applicability; source creation after the as-of snapshot is excluded.
Effective starts/ends and explicitly declared successor effective dates constrain the
rule at the event date. An old source remains usable if still applicable; superseded
sources need a verified interval covering the dated claim. Undated formal rules require a
reviewer's temporal basis. CSV date extrema are extraction metadata, not an automatic
interpretation of what each date column means; reviewers must verify the relevant event.

Prescribed rules, actual practice and recorded state remain distinct. A practice departure
from policy is presented as divergence, not as disproving the policy's prescription. Formal
policy alone does not establish actual behaviour or a recorded field value. Operational
rows alone establish only what is recorded. An actual/intended-state interpretation needs
reviewer justification and separately referenced corroborating reviewed evidence from
another origin. Uncertain correction notes can remain qualifications and data-quality
concerns; no correction is automatically promoted to fact. Missing approval records never
establish that approval did not occur.

A responsible role requires an exact quoted excerpt and reviewer validation, and must be
applicable to the assessed period/scope. Source ownership/authorship graph metadata is not
itself evidence of decision rights. When no applicable role is documented, the result says
so. Source-grounded settlement requests explain what additional evidence is needed.

## Results, knowledge risks and sensitivity

Completed results expose the claim, scope/clarification context, date, verdict, confidence,
explanation, support, contradiction, qualification, contextual evidence, policy–practice
differences, excluded evidence and reasons, origin groups, gaps and settlement requests.
They never convert a verdict to an automatic Yes/No response.

Risk flags combine deterministic material conflict/origin repetition with explicitly
reviewed stale-belief, decision-rights, data-quality, divergence and gap findings. Every flag
identifies the claim, completed review and evidence IDs. No-candidate assessments cannot
produce invented evidence links. The dashboard is a view of assessment coverage, not an
exhaustive transaction audit or automatic breach detector.

Sensitivity removes one source origin group or changes the materiality threshold to 0.4,
0.5 or 0.6, replaying the same snapshot and reasoner. Baseline and alternative verdict and
confidence plus rule traces are shown. Neither baseline review records nor results change.

The standalone HTML print report escapes untrusted text, includes full excerpts and
references without truncation, and permits content to flow across printed pages. JSON
export retains the detailed assessment and review snapshot. Automated checks cover a long
excerpt's final marker and unrestricted print-flow CSS. Browser print pagination still
needs visual verification on the presentation machine; no connected browser was available
in this implementation session.

## Experimental and evaluation boundary

Earlier free-question interpretation experiments remain research artifacts:
`interpretation.py`, `interpretation_v1.py`, `interpretation_v2.py`, `query_frames.py`,
`query_intents.py`, `structural_normalization.py` and `evidence_binding.py`, alongside their
results and tests. Interpretation 1.3's llama3.1/Qwen development gates failed. Stage 2A
was an unpromoted retrieval-first intent spike with no demonstrated live-model accuracy.
Stage 2B has not been implemented or activated. See the existing interpretation documents
for the original experimental record.

The audit found scenario-oriented parsing and relationship rules in `approach_b.py` and
its older interpretation path, plus a pending evidence binder in `evidence_binding.py`.
The employee workflow does not import or invoke those components. Their automatic links
cannot become application human reviews. A new generic bounded intake and explicit human
relationship pipeline replace that dependency in the employee flow; historical experimental
behaviour is preserved for research comparison rather than rewritten to improve its scores.

Approach A remains the reviewer-led lexical baseline; Approach B remains experimental.
The shared retrieval eligibility and same-origin counting fixes are documented implementation
changes, not evidence that either approach has won formal evaluation. No held-out reference
labels, expected relationships or verdicts were used to implement this workflow. No formal
held-out evaluation was run and no forthcoming Phase 3 references were ingested.

## Verified development demonstration

The following is **known development material**, not an unseen evaluation case.
The source was inspected directly in the active Phase 2 ledger:

- `phase2:POL-01`, `EV-9cbd6c4c8c261136`,
  `heading:POL-01 — Discount Approval Policy > Formal requirements#block:001`,
  effective 2025-03-01, explicitly specifies the 15% new-business discount threshold,
  written approval before Closed Won, the named approving role and the CRM record requirement.
- `phase2:POL-02`, `EV-f57003f76db37fcf`, is the superseded instruction, effective 2021-06-01.
  It is a useful historical-applicability inspection example, not a current threshold.

A short demo sequence:

1. In **Assess a Claim**, submit: “The policy requires written approval before Closed Won
   for new-business discounts of 15% or greater.” It enters evidence review without routine
   field confirmation. No verdict is fabricated.
2. In **Evidence Explorer**, search `new-business discount written approval 15%`; inspect
   POL-01's complete formal-requirements block and the supersession graph. Explain that
   other hits are candidates, not established support.
3. Before presenting a completed result, a named human reviewer must review the complete
   candidate packet under **Claim evidence review**, including scope, dates and exclusions.
   Record the approving role only from its exact excerpt. Complete the review and mark the
   claim reusable only after meaning review. The repository is deliberately not seeded
   with fabricated human reviews.
4. Open that result in **Claim Register**, inspect evidence/gaps and remove its decisive
   source group in sensitivity; export the HTML report. **Knowledge Risks** shows only
   concerns actually recorded in this review, with evidence links.
5. Submit an unfamiliar claim such as “Xylophonic widgets shall oscillate extraterrestrially.”
   It can be registered without an invented answer. Show unresolved wording, such as “They
   must inspect turbines.”, staying in clarification rather than receiving a verdict.

For reproducible software-only demonstration of a complete reviewed path, run
`uv run pytest tests/test_claim_first.py tests/test_claim_first_ui.py -q`. These use explicitly
synthetic maintenance instructions and independently specified test-review judgements;
they do not install fake reviews into the real corpus ledger.
