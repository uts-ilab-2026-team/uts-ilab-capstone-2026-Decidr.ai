# Conversational employee assessment

The employee **Assess a Claim** page now uses a durable SQLite conversation and one chat input. A resolved statement automatically produces an assessment message containing the existing reasoner's verdict, qualitative confidence, explanation, evidence groups, source links, expandable graph/audit, and report downloads. Optional human review appears after the verdict and requires an explicit click. Research/admin navigation and the original register/reviewer tools remain available.

## Reproduction and diagnosis

Reproduced with the existing intake before editing:

> Customer-onboarding travel follows the normal expense approval route.

The employee workflow calls `claim_intake.interpret_claim`, not the experimental question interpreters. Its verb expression omitted `follows`, producing “Please state who or what does the action, and what the action applies to.” It never reached source retrieval. Merely adding the verb exposed a second issue: the sentence can assert written policy or actual practice, which materially differ in the sources.

The intake recognises `follows`. For the bounded general expense-route proposition, eligible ledger excerpts explain the terminology and are retained in interpretation provenance. The original sentence remains the assessed claim; no approver, amount, route step, receipt requirement or exception is inserted into its wording. Assessment now proceeds immediately across written rules, reported practice and recorded events. An unspecified target is stored as `null`, not silently interpreted as a prescribed rule. Explicit policy, practice and recorded-state wording retains its scope.

“Both”, “all” and “I want your interpretation” select all relevant evidence and proceed. Saved category-gated entries can resume even if they already contain one of these responses. Completed historical assessments remain immutable. Category selection is absent from employee intake; source categories appear in the answer and exports.

The Phase 2 source reproduction, using a temporary ingested ledger, establishes:

| Intended meaning | Existing reasoner outcome | Relevant source basis |
| --- | --- | --- |
| Written expense policy | Supported | POL-07 applies to all employees submitting expense claims, requires Finance & People Ops approval above $500, permits direct-manager approval at $500 or less, requires itemised receipts, and documents no exception in that version. |
| Actual practice | Contradicted | PROC-04 reports standing pre-approval for customer-onboarding travel; INT-03 and INT-06 describe booking without separate sign-off. |

Practice reported inside a process document remains observed-practice evidence. It does not become a formal policy amendment. The classifier freezes comparisons for each target and applies the existing reasoner separately. The overall verdict for the travel example is **Mixed findings**: written rules support the claim while reported practice contradicts it. This is policy–practice divergence, not a direct logical contradiction. **Contested** is reserved for material support and contradiction within an assessment target. Missing scope or modified claim conditions cannot inherit the supported route classification.

Retrieval covers eligible source types without a category filter, with a 50-candidate limit and source-provenance expansion. The answer explicitly reports this bound and whether it was reached. Unsupported comparisons and classifier errors retain their evidence IDs, excerpts and failure reasons separately from evidence gaps. Available verdicts remain visible with provisional wording and lower confidence when coverage is incomplete. Each target has separate evidence, scope and reasoning; record values alone do not establish intended or actual state.

## Continuity and provenance

- Messages and assessment references persist in `employee_conversations` and `employee_messages`. Saved conversations, URL reopening and register-to-conversation links resume the same history.
- Clarification responses are retained alongside original wording. A complete explicit restatement or a bounded, explicitly supplied subject reference records the interpreted claim and its transformation basis.
- Supported follow-ups read only the selected assessment's frozen evidence. Source, contradiction, exception and explanation requests cannot alter a verdict. Contextual practice contradictions remain visible with their actual classification.
- New topics receive separate claim entries and no revision link. Explicit corrections and the same proposition with changed values or polarity receive new entries linked to the selected parent assessment. Sharing a subject alone does not establish a revision. Parent links persist in the run and export provenance. Conversation messages never enter evidence retrieval, classification or credibility scoring.
- Original system assessments and subsequent human reassessments remain separate. Earlier follow-up answers continue to point to the snapshot they used.
- Assessment source links and graph links carry the assessment identifier. The source page reads the frozen excerpts, even if the live source ledger subsequently changes. Returning from a source retains the conversation identifier.
- Failed message processing rolls back the turn rather than leaving partially created claims or runs. Reopening synchronises completed assessments without duplicating them.

The discount/support-ticket contamination came from routing every message to the first pending clarification. A complete new statement could replace that entry's interpreted claim while inheriting its old original wording. Routing now considers only the active claim, accepts bounded explicit referent resolutions, and sends new statements through separate submissions. UI, JSON and HTML read original wording and interpretation provenance from the frozen run. Tests reproduce pending support-ticket → discount transitions and verify claim text, query, evidence, entry/run links and exports together; existing completed history is not rewritten.

## Verification and limits

Verification uses the actual Phase 2 sources in temporary databases plus independent synthetic fixtures and Streamlit `AppTest` interaction tests. Coverage includes automatic results, targeted and free-text clarification, one message input, multiple statements, saved conversations, fresh-session reopening, source round trips, frozen source excerpts after ledger changes, revised claims, follow-up isolation, invalid cross-conversation links, rollback, and immutable original/human assessments.

Validation includes full-suite pytest, scoped classification and classifier-error regressions, legacy “both/all/interpretation” replies, topic changes, revisions, mixed evidence, claim-to-export identity, and Streamlit interaction checks. Tests use temporary ledgers and do not alter live employee history.

This remains a bounded local research prototype. It is not a general-purpose conversational LLM. Follow-ups recognise explicit source/contradiction/exception/explanation requests; unfamiliar questions and incomplete changed claims require clarification or a complete statement. The added expense-route comparison is deliberately bounded to the full general-route proposition and explicit source scope, not a universal policy-language interpreter. Unknown evidence relationships remain unclassified, retrieval is bounded, and confidence is qualitative. Reviewer names remain audit identifiers, not authentication.

Interaction verification used Streamlit's test runtime, without a live browser session. No live employee ledger was altered for verification. Existing staged and unstaged work was preserved; no commit or push was performed.

Changed for this task: `app/employee.py`, `decidr/claim_intake.py`, `decidr/claim_workflow.py`, `decidr/automatic_evidence.py`, `decidr/claim_graph.py`, new `decidr/conversation.py`, updated `tests/test_claim_first_ui.py`, new `tests/test_conversation.py`, and this report. These build on existing uncommitted employee-workflow files.
