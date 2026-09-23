# Assessment quality and presentation — development validation

> **Metadata follow-up:** This page records the original development run. The
> [separate corrected dataset](source_metadata_correction.md) reuses its outputs and preserves
> all original artifacts. Shared applicability improves; semantic relationship failures remain.
> Both alternatives stay disabled. Independent research adjudication follows system output.

The presentation changes and historical-applicability fix are implemented. The bounded classifier **does not reliably handle the requested semantic distinctions**. Its limitations are exposed, and the evaluated local-model alternative is **not enabled in production**. No verdicts, claim IDs or expected labels were added to runtime classification.

## Provisional expected findings from actual passages

All diagnostic passages come from `data/raw/phase2_model_development`. These are author-established development expectations, not independent reviewer agreement or held-out accuracy.

- **Explicit unassignment versus missing information.** The decision-rights table says the final call on renewal disagreements is “**Not assigned to any role**”. That contradicts a claim that a role has been formally assigned; it supports the negated and paraphrased unassignment claims. Its onboarding-deviation row says “**Not formally assigned**” while describing the Head of Customer Success & Delivery's informal practice. Those are separate findings. The QA role description instead says release-blocking rights are not formally documented and that the description does not address them: this does not establish that the role has no authority.
- **Ticket closure.** PROC-05 step 6 states: “Support Lead confirms resolution with the customer and closes the ticket.” POL-04's proposed requirement allows Support Reps to close after customer confirmation without Engineering sign-off, but the draft is explicitly not in force. INT-07 reports that reps do so in practice. That testimony cannot establish formal approval of the draft. Closing after engineer assignment changes the completion condition; limiting closure permission to Severity 1 changes the scope of a rule whose closure clause is not severity-limited.
- **Discount boundaries and exceptions.** POL-01 requires written Finance approval at **15% or greater**, before Closed Won, with no formally documented exception. Exactly 15% is included; “above 15% only” changes the boundary. An urgent deal reported in communications does not amend the formal rule. Renewal discounts instead have a 10% cap against the current contracted rate under POL-06. The old POL-02 threshold is applicable only within its historical effective interval.
- **Start and completion events.** POL-03 times standard onboarding completion from assignment. PROC-01's productive-use purpose starts from contract signature. Neither the start events nor completion events can be treated as interchangeable. Complex-account extensions qualify the standard rule without negating it.

The [46-row comparison matrix](../reports/assessment-quality-development/comparisons.md) includes equivalent paraphrases, negation, inclusive/exclusive thresholds, exceptions, business populations, completion/start events and historical dates. Full passages, exact model responses and provisional expectations are retained in its linked JSON files. Source references in these diagnostic artifacts are development selectors, never runtime dispatch keys.

## Semantic results — separate from workflow verification

| Family | Comparisons | Bounded classified / expected matches | Local alternative classified / expected matches |
|---|---:|---:|---:|
| Authority | 9 | 0 / 0 | 7 / 5 |
| Ticket closure | 14 | 1 / 1 | 14 / 8 |
| Discounts | 17 | 4 / 4 | 15 / 13 |
| Onboarding | 6 | 6 / 4 | 5 / 3 |
| **Total** | **46** | **11 / 9** | **41 / 29** |

The final bounded classifier has **23.9% classification coverage**, **9/46 expected matches**, **2 classified mismatches**, and **35 abstentions**. The classifier version change does not improve those pairwise counts: it corrects temporal applicability of already comparable historical passages. The two classified mismatches remain onboarding completion-event and all-without-exceptions variations being treated as context instead of the provisional qualification finding.

The concrete evaluated alternative is **local Qwen3.5 9.7B Q4_K_M (`qwen3.5:latest`)**, Ollama `/api/chat`, temperature 0, thinking disabled, 8192-token context, 650-token response limit, JSON output. Model digest: `6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7`. It receives claim, target, as-of date, complete passage, source metadata and frozen same-source context; it receives no expectations. A response is accepted only with an allowed relationship, effective-status value and an exact quote from the selected passage. The full prompt and responses are in [alternative.json](../reports/assessment-quality-development/alternative.json).

Its **89.1% validated classification coverage** comes with **29/46 expected matches**, **12 accepted mismatches**, and **5 rejected responses**. Date-status matches are **28/46** after validation. A quote grounded in text does not validate the inference drawn from it. Notable accepted failures:

- Row 1 returns `support` for assigned authority while its rationale itself describes unassignment and contradiction.
- Row 7 misses the negation of informal practice.
- Row 21 promotes interview testimony into formal authority.
- Row 38 treats the assignment delay as negligible, incorrectly supporting a six-week clock from signature.
- Row 39 invents equivalence between recorded completion and productive use.
- Row 45 treats an expired policy's relationship as contradiction, conflating meaning with temporal eligibility.

Rows 8, 9, 40, 41 and 46 fail quote validation; some quote context rather than the selected passage, omit exact Markdown characters, or provide no usable quote. Other mismatches include provisional `qualify` versus model `contradict` and draft semantics versus effectiveness. These require adjudication and are not all equivalent in severity. The expected relationship deliberately compares the wording separately from its effective status.

**Architectural conclusion:** literal grammar plus source-type gating cannot interpret arbitrary authority assignments, table columns, deontic negation, scope restrictions or event relations. More wording patches would not establish generalisation. The evaluated model raises coverage but is also unsafe as a decisive replacement. A future candidate should extract separately cited authority status, actor/action, rule/practice mode, quantifier/boundary, condition, start event, completion event and effective interval, then use deterministic applicability checks. That proposed extraction architecture is **not evaluated here**; it must beat the frozen development matrix, with fresh development paraphrases and independent adjudication, before replacing the current comparator. Production continues to expose abstentions and keep human correction after the provisional verdict.

## Historical applicability fix

`bounded-evidence-5` no longer treats `SUPERSEDED` in a parent document title as a qualification of every passage. Only an actual history section changes the semantic classification. The shared reasoner retains responsibility for effective intervals, successors and draft status. This transfers across sources without a policy ID or claim ID branch.

The [separate temporal gate checks](../reports/assessment-quality-development/workflow-and-time.json) use literal passage claims to isolate date gates from paraphrase failures. They cover POL-01 before/on its effective start, POL-02 within/after its historical interval, the POL-04 draft and PROC-05's missing effective date. **6/6 now agree**; before the fix the historical POL-02 check failed (5/6). Missing effective dates remain unknown; no last-updated date is silently promoted to an effective date. These six checks are not evidence of successful end-to-end paraphrase handling.

## Shared response and graph

Chat and the register call the same renderer. Newly produced results persist `presentation`, containing target-specific findings, ordered sections, comparison coverage, genuine gaps, classification failures, retrieval limits and cited recommendations. Chat follow-ups, graph and HTML exports read the same saved findings. Each target/evidence pair retains a finding ID, relationship, disposition, reason and comparison excerpts. The legacy flat `evidence_dispositions` compatibility field remains in JSON; the presentation's target-specific findings drive the new views, so the flat field does not collapse graph targets.

Order: direct claim answer/verdict → supporting sources → contradicting sources → exceptions/practice differences → evidence gaps → recommended next action → expandable graph. Exact passages and source links are rendered with target labels. Recommendations refer to finding IDs, recorded gap IDs or the recorded retrieval-limit finding. Unclassified candidates are present evidence awaiting classification, not evidence gaps. Exceptions, temporal exclusions and repeated origins remain inspectable. Human review still follows the verdict and creates a new snapshot.

Graph node labels wrap without truncating text; edges retain target and assessed relationship even when excluded. Target/disposition filters and shown/total counts disclose candidates filtered out, evidence omitted by the node bound and omitted provenance nodes. DOT download retains those edge attributes in the visible labels. HTML exports include a filterable source → excerpt → target relationship view and every frozen excerpt, including those outside the app's bounded graph. HTML source links open self-contained frozen details; app links retain `assessment`, `source` and `evidence`. Provenance sources without captured excerpts disclose that fact instead of reading live source text.

Historical results keep their saved verdict. A read-only layout adapter displays old snapshots without writing or reclassifying them. The app identifies older selections and older conversation assessments as historical; new snapshots record creation time separately from their assessed-as-of date. Standalone exports identify a saved frozen result and never claim to know whether it is the latest result in a live ledger.

## Reviewable development artifacts

| Claim | Saved automatic verdict | Classification coverage | Report |
|---|---|---|---|
| Standard onboarding within six weeks | Supported, provisional | 41/50 selected-target comparisons | [HTML](../reports/assessment-quality-development/onboarding.html) |
| Current new-business discount threshold 15% | Supported, provisional | 3/150 comparisons across three targets | [HTML](../reports/assessment-quality-development/discount.html) |
| Reps may close after customer confirmation without Engineering sign-off | Insufficient evidence | 3/150 comparisons across three targets | [HTML](../reports/assessment-quality-development/ticket.html) |

Each retrieved packet contains 50 candidates and reaches its retrieval limit. Coverage includes recognised context and exclusions; it is **not decisive-evidence coverage or accuracy**. Matching assessment JSON, graph JSON and DOT accompany each report. These runs were created in temporary development ledgers; they are not appended to the user's working ledger. The reports are self-contained; their temporary run IDs are provenance, not live application inspection links.

## Verification and preserved work

- Full repository suite: **397 passed**. Ruff passes for the changed runtime modules; `git diff --check` passes. These checks are separate from the semantic scores above.
- Workflow tests exercise target-preserving graph edges, bounded and empty filters, count reconciliation, recommendation references, report anchor integrity, full excerpt escaping, shared rendering, snapshot immutability, temporal title handling and post-verdict review.
- Streamlit's test harness verifies the rendered application structure, verdicts, excerpts and source link parameters. Browser discovery returned no available browser, so live click behaviour, final visual layout and print pagination were **not independently browser-verified**.
- Development refreshes assert that the original run is unchanged. Existing staged and unstaged work was preserved. The working SQLite ledger, held-out evaluation data and portfolio labels were not changed. Nothing was committed or pushed.

Runtime files: `decidr/automatic_evidence.py`, `decidr/assessment_snapshot.py`, `decidr/claim_workflow.py`, `decidr/claim_graph.py`, `decidr/graph.py`, `decidr/claim_export.py`, `decidr/conversation.py`, `app/employee.py`. Regression assertions were added/updated in `tests/test_assessment_snapshot.py`, `tests/test_onboarding_assessment.py`, and `tests/test_claim_first.py`.

Reproduce development comparisons with `.venv/bin/python reports/assessment-quality-development/evaluate.py --output current-bounded.json`. `--ollama` reuses saved responses for identical cases and calls the local model only for missing cases; use a fresh output directory/copy and remove the saved response cache when a completely fresh model evaluation is intended. Generate isolated workflow artifacts with `.venv/bin/python reports/assessment-quality-development/snapshots.py`. Run workflow verification separately with `.venv/bin/pytest -q`.
