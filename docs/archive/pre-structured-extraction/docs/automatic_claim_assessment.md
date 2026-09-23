# Automatic employee assessments

The employee workflow now produces a system assessment before human evidence review.
The archived Approach B overlap/scenario classifier and pending query binder are not
used. `automatic_evidence.py` supplies bounded, span-grounded comparisons to the existing
seven-dimension credibility framework and deterministic verdict reasoner.

Submission or reopening calls `ensure_system_assessment`. Resolved claims retrieve a
bounded lexical packet plus explicit source-provenance neighbours, classify each unit,
and save a completed system snapshot. Unresolved references, scope and target ambiguity
still require clarification. Explicit approval-threshold statements now resolve as
prescribed rules; untouched pending claims from the older parser are refreshed with an
audit event, not a fabricated employee clarification. Submitted clarification is preserved.

Supported automatic comparisons include complete literal propositions, explicit opposite
polarity, numeric equalities for the same single-valued property, and explicit inclusive
approval-boundary rules with matching measure and business scope. Values, scope, polarity,
conditions, and source type matter. Retrieval scores are never used to select relationships.
Unrecognised comparisons remain explicitly unclassified, with no asserted relationship.
They are classifier limitations, not missing evidence or applicability failures. Explicit
process context is classified separately and cannot establish a verdict by itself.
Uncertain, conditional or internally conflicting units remain qualifying.

Credibility scores are visible system assumptions about relevance, documented approval,
directness, dates, provenance, completeness and applicability. The existing reasoner still
applies effective periods, supersession, source dependence and separation of prescribed
rules, recorded state and observed practice. The date defaults to the eligible corpus
creation-date snapshot; where none is available it uses the current UTC date and records
that convention. A result of `Insufficient evidence` is displayed as **Insufficient**.
Missing evidence is never treated as contradiction.

System decisions use `method=automatic`, `review_status=not_reviewed` and live in the
immutable assessment snapshot. They do not create human evidence-link or review rows.
The UI displays the verdict, separate review status, confidence, explanation, evidence,
classification rationale and exact spans. Source links open eligible source excerpts and
provenance through the application, including for local-file sources.

Each subsequent human confirmation/correction records the reviewer, reason, changed
relationship/applicability/credibility, and before/after records. It creates a completed
child assessment with `parent_run_id` and `system_run_id`. Unchanged evidence retains its
original provenance. The history selector and comparison table expose the original result
and reassessments. Partial review does not block any verdict. Failed/proposed changes do
not publish a reassessment. Existing historical human-only assessments are retained.

Limitations: this is a conservative grammar-based classifier, not general semantic
entailment. Unfamiliar paraphrases, implicit exceptions, structured-field interpretations,
undocumented authority or dates can leave claims Insufficient or with lower confidence.
The bounded search is not exhaustive. Independent origins are not statistical independence.
These tests demonstrate processing and traceability, not measured classification accuracy
on unseen data. Human corrections use the frozen corpus revision; after a source-ledger
change, submit a new claim assessment or restore that revision before correcting it.

Verification:

```
.venv/bin/python -m pytest tests/test_automatic_assessment.py tests/test_claim_first.py tests/test_claim_first_ui.py tests/test_reasoning.py tests/test_retrieval.py tests/test_approach_a.py tests/test_exports.py -q
```

Fixtures cover all verdicts, numeric/polarity/scope/target/date safeguards, no-human-row
system processing, idempotent reopening, actual Streamlit submission and clarification,
source pages, and immutable original/parent/child reassessment history.


The second classifier version also compares passive completion requirements, including
written-number durations, `must`/`shall`, `completed`/`finished`, and equivalent week/day/hour
units. It preserves population, polarity, bounds and starting events. Descriptive wording
becomes a requirement only inside an explicit policy/procedure rule section. Different
upper bounds alone are not contradictions. Domain scope distinctions use passage content
and source titles, never source IDs, candidate counts, reference labels or expected verdicts.

Same-source header and exception excerpts are frozen alongside each retrieved passage.
Their IDs and full text are available in source details and exports. Contextual procedure
passages without effective dates can explain the process, but cannot independently
establish an effective rule. CSV rows and separate communications entries retain separate
origin keys; documented source copies/derivations still connect corresponding records.
Context passages from one origin remain visible without becoming independent votes.

`evidence_dispositions` records each candidate as used, excluded or unclassified, with a
separate decisive flag. The graph, result page and export use these final dispositions.
Classification limitations and actual coverage gaps have separate fields. The main result
shows a concise reason and evidence; detailed traces and exclusions remain expandable.
Automatic refresh appends a new assessment of the frozen packet, with a parent reference
and transaction rollback on failure. It never replaces an earlier automatic or human run.

See [the onboarding investigation](onboarding_assessment_investigation.md) for the actual
20-candidate packet, scope distinctions, verification and preserved history.
