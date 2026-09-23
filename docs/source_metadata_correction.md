# Source metadata correction — development v1

Both experimental alternatives remain disabled. The bounded classifier is unchanged at
`bounded-evidence-5`. Ingestion and the metadata constraints used by applicability checks
have been corrected; the working ledger and saved assessments have not been refreshed.
Independent research adjudication is the next step. No extraction redesign or new model
experiment was run.

The corrected dataset is [metadata-correction-development-v1](../reports/metadata-correction-development-v1/README.md).
The [reviewer packet](../reports/metadata-correction-development-v1/reviewer-packet.html)
contains every disputed development claim, its exact addressed passage, same-source context,
original proposed labels, model values/citations and the specific disagreement. It supports
research evaluation **after system output**. It adds no employee pre-verdict review gate.

## Root causes and corrections

PROC-05's exact header says:

> - **Approval status:** Approved. This is the current formally approved version. (See POL-04 for an unapproved draft revision.)

`build_source` previously searched the whole approval value for `draft`. The reference to
POL-04 therefore overwrote PROC-05's own status. The parser now attributes approval clauses
to the containing document or a referenced document. PROC-05 becomes `current`; the original
approval string remains intact. POL-04 remains `draft`. No effective start is documented for
PROC-05, so its formal-rule applicability remains `unknown`, not `yes`.

POL-02's exact header says:

> - **Effective date:** 2021-06-01
> - **Superseded date:** 2025-02-28
> - **Superseded by:** POL-01 (v3.0)

Ingestion never mapped `Superseded date`. It is now retained as `superseded_date=2025-02-28`,
with exact header evidence, independently of `effective_end_date`, which stays null.
The successor declaration is resolved separately from its dates. POL-01's own header says:

> - **Effective date:** 2025-03-01
> - **Supersedes:** POL-02 (v2.1, effective 2021-06-01 – 2025-02-28)

These statements do not settle whether POL-02 remains effective on 2025-02-28. Before that
date its documented start permits the historical diagnostic; after it the old policy cannot
establish a continuing rule. On that date the result is **unknown**. No day is added or
subtracted to manufacture an effective end. The new metadata constraint takes precedence
over the older successor-based historical allowance at the disputed boundary.

All seven procedures also had `Last updated` misrepresented as `creation_date`. The dates
now occupy `last_updated_date`; creation and effective dates stay unspecified. Exact values:

| Source | Last updated (removed from creation date) | Other correction |
|---|---|---|
| PROC-01 | 2024-01-20 | — |
| PROC-02 | 2022-08-15 | — |
| PROC-03 | 2023-11-02 | — |
| PROC-04 | 2021-09-10 | — |
| PROC-05 | 2021-02-10 | lifecycle draft → current |
| PROC-06 | 2022-11-01 | — |
| PROC-07 | 2024-07-05 | — |
| POL-02 | — | superseded date null → 2025-02-28 |

The header reader previously continued into a body section if it had not yet found metadata.
It now reads only the opening header and stops at body prose or a subsequent heading, even
when the header is empty. This latent mechanism produced no additional populated-field
correction in this corpus. Repeated conflicting fields, contradictory own approval statements,
invalid/ambiguous dates and conflicting successor declarations are retained as unresolved
metadata, not resolved by first/last match. Missing approval still carries the existing,
explicitly labelled active-directory lifecycle inference; it is not documentary proof of approval.
This remains bounded header parsing, not reconciliation of arbitrary prose throughout a document.

## Corpus audit and version boundaries

The audit covers all **45 active Phase 2 files**, including excluded documentation. Eight
sources have 16 substantive field changes listed above. All registered sources receive a
metadata parser version; Markdown header entries retain exact lines, source IDs, line numbers,
character offsets and document references. Every field and provenance delta is recorded in
[metadata-corrections.json](../reports/metadata-correction-development-v1/metadata-corrections.json).
Header offsets address UTF-8 decoded source text with any BOM removed and original line endings
retained; approval clause offsets address the exact header value. All 812 evidence units retain
their original identities, locators and text.

The same read-only audit across **23 inactive Phase 1 files** finds the same PROC-05 and seven
update-date defects. Phase 1 remains excluded from modelling. No other active header date/status
conflicts were found. POL-03's version-only `Supersedes` declaration lacks a resolvable document
identity and is explicitly retained as unresolved. The archived org-chart's prose reference
remains prose evidence; it does not supply an inferred supersession date or effective interval.

`INGESTION_VERSION` is now `ingestion-v3-document-metadata`; each source records
`document-metadata-v1`. The raw-corpus fingerprint remains unchanged, so the corrected dataset
also records its own version, hashes and parent matrix hash. Existing corpus/portfolio freeze
compatibility must not be inferred from the raw checksum alone. No working ledger rebuild,
portfolio amendment or snapshot migration was performed.

## Fixed-output comparisons

All 62 claims, passages, contexts, component annotations, relationship labels and expected
date labels are unchanged. Saved bounded outputs, direct-model answers, raw extracted
components, validated components and citation failures are reused byte-for-byte. These are
counterfactual metadata replays, not new model outputs on corrected prompts. In particular,
old citations to serialized metadata still refer to the original input; they are not recertified
against the corrected metadata. No model calls were made.

| Measure | Frozen 46: before → corrected | Fresh 16: before → corrected |
|---|---:|---:|
| Shared applicability / provisional label agreement | 41 → 46 | 15 → 16 |
| Candidate interval check / provisional label agreement | 41 → 46 | 15 → 16 |
| Bounded downstream verdict matches | 32 → 32 | 9 → 9 |
| Direct-model downstream verdict matches | 40 → 41 | 14 → 14 |
| Structured downstream verdict matches | 26 → 26 | 9 → 9 |

Metadata changes alone under the **unchanged old date gate** yield 61/62 date matches:
five PROC-05 cases change `no` to `unknown`. Reading the newly retained superseded-date
constraint fixes frozen-45 and yields 62/62. The extra before/on/after boundary checks are
separate from that score; the on-date check is unresolved. Agreement with author-proposed
labels is not independently validated temporal accuracy.

Only frozen-45 changes a downstream verdict: the direct model's unchanged `contradict`
relationship now yields `Insufficient evidence` rather than `Contradicted`, because the policy
has expired. Direct-model verdict matches rise 54→55/62 and wrong decisive verdicts fall
7→6. This is an applicability correction, **not a repaired semantic inference**. Serious
relationship failures masked by a matching downstream verdict rise from six to seven.

Relationship coverage/matches remain bounded **14/9**, direct model **56/40**, structured
**3/0**, out of 62. The direct model retains three polarity reversals and ten false-decisive
relationships against provisional labels. The structured candidate still produces insufficient
evidence for every case; its 35 matching verdicts are unresolved examples. Ticket closure
misread as `closed_won`, formal/practice confusion, wrong authority-table row selection and
condition/event/boundary disagreements remain semantic failures or adjudication disputes.

Replaying the saved onboarding, discount and ticket **50-candidate packets** with their exact
saved per-target notes retains verdicts Supported, Supported and Insufficient evidence.
Unclassified comparisons remain 9/50 per onboarding target and 49/50 per discount/ticket target.
The draft policy exclusion reason is now explicit. Retrieval, classification and credibility
were not rerun. These three frozen-packet replays do not measure new full-corpus deployment
performance. See [workflow comparisons](../reports/metadata-correction-development-v1/workflow-comparisons.json).

## Labels and reviewer decisions

No labels were rewritten for these scores. Seven metadata-derived component amendments are
proposed separately: `source_assertion.lifecycle` draft→current for frozen-10–13 and fresh-05;
for frozen-45–46 retain `effective_end=null`, add the documented superseded date separately,
and leave boundary semantics unresolved. Independent reviewers must also assess the 135
surviving non-null component disagreements, missing/rejected components and competing
relationship interpretations. Some differences are normalisation disputes, not proven errors.

Each packet entry exposes the submitted claim and target, designated passage and exact context,
proposed and observed labels, addressed component quotations, model rationale, and the specific
question to adjudicate. Reviewers should record accepted/revised/unresolved, cite exact evidence
and explain the decision. A resulting label amendment needs a new dataset version; this packet
is still pending and is not an adjudicated reference set.

The failed experiment, its matrix, prompts, responses, scores and manifests remain research
history. The new preservation audit verifies **416 protected files**, including raw data,
working and historical ledgers, prior report artifacts, configuration, framework and archives.

## Verification

The final repository suite passes **416 tests**. Ruff check/format and `git diff --check`
pass for the changed runtime files. Regression checks cover reference attribution (including
references without policy IDs), absent headers, repeated/conflicting fields, invalid dates,
update-date separation, ambiguous successor links and the unresolved boundary through the
employee reasoner and both research applicability paths. The offline replay test verifies
unchanged labels, seven proposed amendments and original-output reproduction.

The final artifact audit also verifies all **151 exact header entries** and approval-clause
offsets against the sources, all corrected-artifact/runtime hashes, frozen response hashes,
and report links. This is code/content verification; no live browser visual check is claimed.

Changed runtime files are `decidr/source_metadata.py`, `decidr/ingestion.py`, `decidr/models.py`,
`decidr/corpus.py`, `decidr/claim_workflow.py`, `decidr/evidence_b.py` and `decidr/approach_a.py`.
Regression coverage is in `tests/test_source_metadata.py` and `tests/test_metadata_replay.py`.
The experimental runtime and bounded classifier are unchanged. Nothing was enabled, committed
or pushed.
