# Automatic approval-rule assessment

Built against `review/corpus-assessment-frontend` at
`f944a29d4c52450849d99bfb18882e54e2024399` (the supplied Git archive).

The corpus screen now accepts a claim and an explicit assessment date, with the
existing optional scope clarification. “Assess claim and save result” generates
the interpretations and runs the existing credibility adapter. No prepared
judgement JSON, model service, paid model, new dependency or network inference
is required. Existing cards, typography, colours, evidence details and scope UI
are reused. The prepared-input API and component remain available for existing
clients, but are no longer the primary corpus screen entry.

## Contract

- `POST /api/corpus/assess-automatic` accepts the existing interpretation request
  (`claim`, optional `facet`/target, required `as_of`, bounded retrieval limits).
  It returns an unsaved automatic facet assessment.
- `POST /api/assessments/automatic` additionally accepts `request_id`. It saves
  the automatic result, exact evidence and source snapshots, interpretation and
  authority context, configuration and implementation hashes. The frontend uses
  this endpoint. Configure `DECIDR_CORPUS_DB`, authentication and a separate
  `DECIDR_ASSESSMENT_DB` as documented in `assessment_history.md`.
- Human review comes after the automatic result. The form exposes relationship,
  scope, time, authority, quality and rationale fields from the generated packet.
  It saves a reasoned parent-linked revision via the existing history endpoint.
  Independence is conservatively left unverified. Review submissions still
  remain conditional caller declarations, not authenticated authority proofs.
- Reviews use the current index, as the existing history contract specifies;
  the parent snapshot is never recomputed. Changed citation text fails validation.
  Idempotent retries return the original frozen result even if the corpus changes.
  Export and owner-scoped history endpoints work for both types of record.

## Automatic boundary

The existing `approval_fields_v2` grammar compares approver, deal scope, discount
range, written approval, timing and event. A supported rule comparison can supply an automatic support relationship when
adjacent statements pass bounded context checks. Recognised context includes CRM
approval recording, an agreeing scope, a non-overlapping lower-discount permission,
and a renewal-policy reference beside a new-business rule. Unknown clauses,
exceptions and overlapping permissions remain unresolved. Exact focal and full
passage citations are retained. These checks do not interpret other document sections.
The result separately reports “Rule wording matches; authority unresolved”; the
credibility outcome and all admission gates remain unchanged. Differences alone never mean contradiction. Unsupported
wording, generic exact-text matches and unsupported targets remain unresolved.
Original claim text and any separate facet are preserved verbatim.

For supported comparisons, directness, specificity and completeness are 1.0 as
binary grammar-coverage dimensions, explicitly not calibrated probabilities.
Other comparisons retain zero dimensions. Retrieval scores never feed credibility.
All original scope, date, lifecycle, metadata-conflict, target and authority gates
remain in the existing adapter. Derived-source inputs remain visible but excluded
until their provenance can be reviewed; the form does not resolve missing parents.

## Bounded authority resolution

`explicit-policy-adoption-v1` resolves documentary authority only when all gates
pass. This is not source authentication and never sets independence to verified.
The grammar deliberately accepts only complete statements such as these (values
are illustrative, not records to add to the corpus):

- `On 2025-02-24, Alex Smith adopted POL-01 version 3.0 for new-business deals, effective 2025-03-01.`
- `Alex Smith has authority to adopt POL-01 version 3.0 for new-business deals from 2024-01-01 through 2025-12-31.`

The first must be a meeting decision; the second a separate organisational
information/role-description record under Decision rights. Policy identity,
version and effective date must match exact stored header citations, with a
current own-document approval assertion. The named person, version and scope must
agree. Rights must cover the decision date and be documented by that date;
the meeting must be recorded by the assessment date. Sources must be ingested,
current, conflict-free and not derived. Known duplicate groups, identical content
checksums and same-source chains cannot establish verification. Unsupported
relevant decisions, qualifications, revocations or ambiguous multiple records
block resolution. All checks and exact citations are retained in the snapshot.

A complete chain can admit a matched policy to the existing credibility engine;
other gates and weights remain unchanged. Human review still follows the result.
Source ownership, titles, transaction-approval rights and general delegation are
not substitutes for policy-adoption rights. General paraphrases, implicit scope,
role occupancy, transitive delegation and historical superseded authority sources
remain unsupported. Do not rewrite corpus records just to fit this grammar.

The resolver also joins a policy's uniquely matching version-history row to a
meeting's dated threshold decision, completed policy-update action, document
owner and named sign-off. These must belong to the same agenda item and agree
on policy identity, version, dates and thresholds. Rejected alternatives are not
adopted decisions. Ambiguous histories, incomplete actions and qualifications
remain unresolved. Exact quotations from every linked record are retained.

For the local Phase 2 POL-01 example, header and documented adoption checks now
pass: the version 3.0 history links to MTG-01 and Renata Voss's sign-off. Explicit,
dated policy-adoption rights are still not established, and other relevant context
requires review. The outcome therefore remains insufficient evidence. The UI
separately explains the documented adoption and remaining gaps. Synthetic fixtures
with explicit matching rights validate the positive path; they do not establish
rights for real corpus actors.

Complete discount-rule claims also accept plural wording and a scope-first form,
while preserving all required fields and the original claim text. Missing scope,
timing or approver is never silently supplied. This is a bounded interpreter, not
a general natural-language authority solver.

One corpus read transaction supplies retrieval, interpretation and scoring inputs.
Saved runs freeze the full validated index so authority-context quotations are
available after index replacement. This favours reproducibility over storage size;
large corpora will produce large snapshots. Limits on retrieved groups and inputs
remain visible and do not imply exhaustive coverage.

## Verification

The supplied baseline reproduced: 748 Python tests and 8 subtests passed.
Current verification: 852 Python tests plus 8 subtests, 14 frontend tests, TypeScript checking, production build, lint and formatting passed.

Added API tests cover bounded support, abstention, exact citations, original claim
and facet binding, no matches, draft/non-approved/future/superseded/derived sources,
authentication, request validation, idempotency, owner isolation, immutable replay
and parent-linked review. Frontend render tests cover the automatic entry and
saved-result disclosure. Run:

```sh
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
cd frontend
npm ci
npx tsc --noEmit
npm run build
npm run test:supplied
```

A live browser interaction/visual comparison and evaluation against an external
production corpus were not performed. No production corpus is in this archive.

The POL-01 regression was also replayed read-only against the local Phase 2 corpus using the exported claim and date: its rule is now support, with authority as its remaining admission blocker. Existing saved runs retain their original results.

## Reviewing missing adoption rights

When adoption is documented but authority remains unresolved, the result now
states the actual policy code, version, scope, decision-maker and decision date
that need verification. Matching named role sections from the same release are
retained as exact review citations, including undated records. These additional
citations never establish authority or independence automatically.

The local POL-01 replay found a CEO role record describing strategic authority
and broad operational delegation, and Finance records describing transaction
approval. These do not establish a dated policy-adoption grant. The CEO role
source has no recorded creation date. Review guidance asks for the applicable
grant/delegation, dates, scope and qualifications, and directs reviewers to record
source/passage identifiers and reasoning in the existing review form. Missing
proof stays unresolved; a human revision preserves the automatic snapshot.

The guidance is derived from evidence fields, not a POL-01 special case. Tests
also exercise POL-42 with a different actor and release, both with and without
explicit matching rights. Rule recognition remains limited to the supported
discount-approval grammar and adoption structures described above.

## Expense approval and cross-family evaluation

Complete expense-approval requirements now compare monetary threshold, strict or
inclusive boundary, currency symbol, approver, written approval and timing before
or after reimbursement. Currency symbols are compared literally: `$` does not
establish AUD or USD and no conversion is performed. Different actors, currencies,
conditions or boundaries do not automatically establish contradiction.

The context checker retains the itemised-receipt requirement and a non-overlapping
manager permission at or below a stated amount. Unknown exceptions or overlapping
permissions block automatic support. Full passage and exact focal quotations remain
available. Expense policies use the same explicit, dated adoption-and-rights checks as discount policies, with an explicit expense-claims scope. Operational wording alone never grants authority.

`evaluation/approval_rules/cases.json` is a small, corpus-shaped development set,
not an independent benchmark or a human-approved truth set. It includes discount
and expense matches, boundary/actor/currency differences, and renewal-cap and
deployment-signoff cases that must remain unsupported. Run it with
`pytest tests/test_expense_approval.py`. API coverage also verifies saved expense
results, exact citations, authority abstention, exception handling and immutable
history. The next rule families remain renewal caps and deployment sign-off.

## Expense-policy authority follow-up

The explicit authority grammar also accepts `for expense claims` in adoption and
rights statements. It preserves version, actor, date, lifecycle, provenance and
conflict gates. The threshold-change/version-history join remains discount-only.

Inspection of local POL-07 found version 2.0 effective 2021-09-01 and operational
approval rights, but no supported adoption-and-rights chain. MTG-09 deferred changes
and selected no option; it is retained for review, never treated as adoption.
New expense assessments now run the shared authority checks and retain linked
records instead of stopping at a blanket unsupported-family message. Missing or
unrecognised evidence remains unresolved. Complete expense chains are validated
with synthetic fixtures, not asserted to exist in the local corpus.
