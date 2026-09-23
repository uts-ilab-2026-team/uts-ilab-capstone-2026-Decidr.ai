# Hardcoding audit — completed before benchmark changes

Audit date: 2026-09-10. Scope: the current working tree, including existing uncommitted
changes. No production implementation was changed during this audit. Phase 3 claim/label
files and held-out portfolio contents were not opened. This is a static audit with
local ledger metadata checks, not a generalisation result.

## Findings

| Priority | Location | Evidence and consequence |
|---|---|---|
| High | `decidr/automatic_evidence.py:35–83`, `claim_workflow.py:257–284` | An exact customer-onboarding-travel proposition invokes special policy/practice comparisons and terminology grounding. Source quotations supply the expense amount, but the interpretation that these particular passages support/contradict this particular scenario is programmed. Equivalent unfamiliar scenarios receive no such treatment. |
| High | `decidr/automatic_evidence.py:166–236` | Completion grammar has customer-onboarding title substitution; context classification contains specific new-hire, renewal, data-handling and complex-account rules. `extension`/`complex` automatically receives an exception explanation. These are business semantics encoded in branches, not general source-derived applicability reasoning. |
| High | `decidr/approach_b.py:122–175` | The fallback parser reads every candidate portfolio row before proposing interpretations, with no split filter. Merely calling it can inspect held-out wording. Its portfolio was deliberately not loaded in this audit or the new benchmark. Employee `claim_intake.py` does not use that portfolio. |
| High | `decidr/approach_b.py:178–257`, `evidence_b.py:144–261` | Discount-specific intake inserts written approval and Closed Won into structured fields. Eligibility has detailed discount/deal/CRM branches, while other processes require literal process/scope/condition substrings. Source-derived numbers do not remove this family-specific advantage. |
| High | `decidr/approach_b.py:507–553` | Relationship inference can promote an approval rule by polarity or token-overlap cutoffs (0.22/0.38). This does not establish matching actors, events, quantifiers and exceptions for arbitrary new claims. |
| High | `decidr/claim_workflow.py:446–452` | Production requests 50 lexical candidates and expands to the same limit of 50. A full lexical packet leaves no capacity for graph additions. |
| High | `decidr/claim_workflow.py:704–719` | Same-source headers and Exceptions passages are attached after retrieval. They are additional evidence exposure outside the nominal passage count. Comparisons that count only ranked candidates have unequal effective budgets. |
| Medium | `decidr/approach_b.py:406–476` | The other graph expander limits depth, not candidate count, and appends entire related sources in ID order. Comparison with a fixed-size lexical packet is not a controlled retrieval ablation. Neither expander traverses independently validated assertion relationships. |
| High | `decidr/evaluation.py:36–69` | With an incomplete reference set, `retrieved - relevant` is still called irrelevant. That set includes unjudged evidence. Existing metrics conflate relevance with applicability and omit document-level, counterevidence and exception recall. |
| Medium | `decidr/ingestion.py:94–100`, `automatic_evidence.py` source-type dispatch | Ingestion emits `meeting`, `project_tasks`, `audit_events`; some downstream type lists expect `meeting_notes`, `task_records`, `audit_logs`. CSV extraction partly compensates; meeting prose has no equivalent fallback. Applicability and relationship errors need separate measurement. |
| Medium | `reports/structured-extraction-development/prepare.py`, `score.py`, `graph_comparison.py` | Development annotations encode known families, roles and thresholds. They are explicitly provisional; single-passage downstream diagnostics and designated-passage recovery do not establish full evidence retrieval or assessment quality. “Fresh” wording in this material is already development-exposed. |

## Existing safeguards and limitations

* Core lexical/semantic retrievers have no discovered claim-ID-to-answer or fixed business
  threshold lookup. BM25, RRF k=60, candidate limits and credibility weights are algorithmic
  settings, not organisational facts; their quality still needs independent validation.
* Phase 2 eligibility is enforced in the employee retrieval route. Ingestion excludes release
  documentation and labelled samples. Explicit source versions and provenance are retained.
* `ensure_system_assessment`, `_save_assessment_snapshot` and `reassess_evidence` preserve
  automatic results and create separate review snapshots. Unclassified candidates remain
  visible; automatic outcomes are provisional. These are workflow properties, not accuracy.
* The active ledger has 45 registered sources, 812 passages, zero adjudications, zero
  claim-evidence reviews and zero employee evidence-review notes. Ten saved system runs are
  not independent references. Counts were obtained without reading held-out claim contents.
* The optional sentence-transformer package and configured model are absent locally.
  A lexical fallback cannot be reported as a semantic/hybrid experiment.
* The existing corpus freeze checks ingestion/corpus and portfolio inputs, but does not hash
  all runtime modules, prompts, models, dependencies and retrieval budgets. It is insufficient
  as the sole pipeline freeze for Phase 3.

## Audit conclusion

The current implementation has substantial development-family specialisation. No evidence
currently establishes generalisation to unseen Phase 3 claims. Preserve this implementation
as a measured baseline; select changes only after full-packet, family-grouped Phase 2
evaluation. The next artifact will define and run that evaluation with provisional source-
grounded pools, explicit unjudged candidates and independent-review gates. Production
behaviour should not be replaced on provisional agreement alone.
