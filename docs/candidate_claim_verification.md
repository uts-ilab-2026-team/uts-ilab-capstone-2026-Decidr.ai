# Candidate portfolio v1.2: interim verification

Date: `2026-09-04`

Status: v1.2-final was approved by Royston on `2026-09-04` and is frozen as a study input. It is
not adjudicated ground truth. Separate blind packets have been generated without outcomes.
Final/held-out evaluation has not been run. The immutable v1.1-final snapshot remains archived.

## Revised claims

| Claim | Verification | Verified directly | Inferred or unverified |
|---|---|---|---|
| CAND-01 | Verified | POL-01 ID/version/status, new-business scope, 15% threshold, written approval, role, ordering, `2025-03-01` effective date | None |
| CAND-02 | Verified | POL-02 ID/version/status, customer-deal scope, 10% threshold, written approval, role, ordering, `2021-06-01` start; POL-01 gives `2025-02-28` end | None. “New-business” was replaced with source-faithful “customer-deal”. Renewal evidence is contextual/qualifying. |
| CAND-03 | Verified replacement | POL-03 v1.4 Approved, all new-business accounts, assignment to an Implementation Specialist, standard completion within six weeks, effective `2024-01-15` | None. The zero-denominator practice claim was replaced by the approved prescribed-standard fallback. Operational delays are contextual divergence. |
| CAND-04 | Assessability verified | Five unique `TICK-*` cases each contain creation and first Engineering-escalation timestamps under the same stable ID. Attribution is to the support function. | The corpus is not known to contain all organisational escalation records. The numerator and held-out outcome remain sealed. |
| CAND-05 | Verified | POL-06 v1.1 Approved, renewal scope, 10% cap, current-contracted-rate basis, effective `2024-06-01` | None. The inferred independent-authority wording was removed from the claim. |
| CAND-06 | Verified | POL-07 v2.0 Approved, employee scope, over-$500 threshold, role, approval-before-reimbursement ordering, effective `2021-09-01` | None |
| CAND-07 | Verified with internal inconsistency | `phase2:org-chart-and-roster` yields one eligible employee, Yusuf Demir, start `2025-09-01`; COMMS-12 dated `2025-09-05` records checklist completion within 14 days | COMMS-12 calls the completion “day 10”, inconsistent with the four-calendar-day difference. Organisational-record completeness is unknown. Result is strictly `n = 1` record coverage, not wider practice. |
| CAND-08 | Assessability verified with evidence gap | `INC-2026-02`, `AUD-0111`, and release timestamp `2026-02-18 16:30`; role description supplies the prescribed Head of Engineering sign-off requirement | No separate `DEPLOY-*` ID and no verified pre-release sign-off status. Missing linked evidence is not automatically proof of no sign-off. Outcome remains sealed. |

## Quantitative eligibility

| Claim | Eligible cases | Denominator |
|---|---:|---|
| CAND-04 | 5 | Unique stable `TICK-*` identifiers with both ticket-creation and first Engineering-escalation timestamps; missing timestamps and duplicate/derived records excluded |
| CAND-07 | 1 | Employees in `phase2:org-chart-and-roster` with start dates from `2025-08-01` through `2026-07-31` |

CAND-04's numerator is intentionally not reported because it is held out. CAND-07 is a universal
record-coverage proposition rather than a routine-practice percentage; its `n = 1` limitation
must accompany any result.

## Completeness separation

- `ingestion_completeness`: 68 sources registered; 65 ingested; the two README files and the
  illustrative labelled-claims sample were intentionally excluded. The ingestion report records
  zero warnings. This is stored as `complete_with_documented_exclusions`.
- `record_population_completeness`: unknown for operational populations unless a claim explicitly
  defines its population from a named supplied record such as the roster. Successful ingestion
  is not evidence that Northfield supplied every organisational record.
- `claim_evidence_coverage`: recorded per claim. All eight are assessable as presently worded;
  CAND-08 deliberately remains assessable despite an evidence gap because multiple verdicts are
  theoretically available to reviewers.

## Frozen definitions and gates

The operational definitions are approved and frozen in `configs/human_study.json`. The reasoning
ruleset remains separately marked `development_unfrozen`. Dates are ISO; ongoing end dates are
empty CSV cells parsed as `None`; applicability periods and the `2026-07-31` assessment cutoff
are separate.

Administrative split remains development CAND-01, CAND-02, CAND-03, CAND-05, CAND-06, CAND-07;
held-out CAND-04 and CAND-08. Packet generation is authorised and complete. Held-out access
remains sealed and final evaluation authorization remains false.
