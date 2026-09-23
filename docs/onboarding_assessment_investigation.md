# Onboarding assessment investigation

Claim: “Standard customer onboarding must be completed within six weeks.”

The saved packet was inspected directly from the local ledger, then compared with the
repository's actual Phase 2 POL-03 and PROC-01 Markdown documents. No portfolio labels or
expected outcomes are read by the runtime. The existing 20 candidates were reclassified;
same-source headers and exceptions were attached as explicit, cited scope context.

## Source meaning and resulting assessment

POL-03 Formal requirements states: “Standard onboarding is completed within **6 weeks**
of assignment.” Its header covers **all new-business customer accounts**, and its
exceptions allow timeline extensions for unusual technical complexity without identifying
the extension approver. Completion additionally requires the checklist to be marked
complete in the project system. These are material scope details of the supported rule.
The claim does not specify the clock origin; the result expressly reports assignment.

PROC-01 Purpose says: “Take a newly signed customer from contract signature to productive
use of Northfield OS within 6 weeks.” Its Steps place go-live in week five and recorded
completion/handover in week six. Its Required approvals section describes complex-account
extensions case by case. This is applicable process/exception context, not an independent
statement with the same start and completion events. The procedure has a last-updated
date but no effective date in the ledger; no effective date is invented.

The automatic reasoner calculates **Supported / Moderate confidence** at the original
2026-07-20 assessment snapshot: **1 supporting, 9 contextual, 10 excluded, 0 unclassified**.
Only the policy requirement contributes decisive support. There is no material applicable
contradiction. Interviews, informal communications and historical policy background explain
the process without proving the prescribed rule or contradicting it through practice.
Employee onboarding, contract renewal and data handling concern different propositions.

## Failure trace and changes

1. Intake correctly retained the original wording and parsed subject `Standard customer
   onboarding`, predicate `must`, object `be completed within six weeks`, target
   `prescribed_rule`. It now also protects the exact written-number duration span.
2. The old comparator understood literal statements, polarity pairs, numeric equalities
   and approval thresholds. It could not compare `must be completed` with the formal
   `is completed`, `six` with `6`, or the source-grounded customer/onboarding wording.
3. Each failure became a `contextual` relationship while scope and condition matches were
   set false. Applicability excluded every candidate. The failure reason was repeatedly
   presented as an evidence gap. Graph edges used the preliminary notes and consequently
   showed 20 contextual relationships even though the verdict used none.
4. The new bounded comparison handles completion paraphrases and equivalent durations,
   retaining population, polarity and clock distinctions. Unsupported wording stays
   `unclassified` with a null relationship and a specific classifier limitation. Known
   irrelevant scopes are excluded; recognised context remains applicable but nondecisive.
5. The shared reasoner applies dates, target, credibility and documented dependence before
   calculating its existing four-way verdict. Context without an effective date is not
   promoted into an effective rule. Different upper bounds alone do not imply contradiction.
6. A single final disposition map drives graph edges and exports; the result's evidence
   buckets supply that same map. Green support, blue context, grey exclusions, red
   contradictions, gold qualifications and purple unclassified edges have readable labels.
   Nodes link to excerpts/source details. Exclusions remain expandable. Diagnostic traces
   and follow-up details are kept out of the main result.
7. CSV row identities and communications entry identities qualify origin grouping, so
   a shared container alone does not merge different records. Documented copy/derivation
   groups remain, and contextual excerpts sharing an origin remain visible without
   increasing decisive corroboration.

## Exact saved packet

| Evidence ID | Source / passage | Final disposition | Relationship |
|---|---|---|---|
| EV-d9cca48dd060a4d3 | phase2:POL-03 / Formal requirements | used | support |
| EV-459cb04dea973068 | phase2:INT-06 / Discussion notes | used | contextual |
| EV-b33423f05b28d36d | phase2:INT-06 / Statements of uncertainty | used | contextual |
| EV-1df4853d8e769e73 | phase2:PROC-01 / Purpose | used | contextual |
| EV-a5fd25e7c63db314 | phase2:POL-08 / Formal requirements | excluded | not_applicable |
| EV-a173c1918d3eb100 | phase2:INT-06 / Discussion notes | used | contextual |
| EV-56d2e26d5c3fc92b | phase2:PROC-01 / Steps | used | contextual |
| EV-ecd7375cfeafce41 | phase2:POL-05 / Formal requirements | excluded | not_applicable |
| EV-65eedf2f07811626 | phase2:communications-log / COMMS-13 — Slack DM | used | contextual |
| EV-3feed06b821c847d | phase2:project-tasks / csv:row:84;task_id:TASK-083 | excluded | not_applicable |
| EV-cb64cb50edde1a4b | phase2:project-tasks / csv:row:21;task_id:TASK-020 | excluded | not_applicable |
| EV-06ab7cd6ed419b16 | phase2:INT-06 / Discussion notes | used | contextual |
| EV-dd0f31d63235aca2 | phase2:project-tasks / csv:row:70;task_id:TASK-069 | excluded | not_applicable |
| EV-beef515ebcab9845 | phase2:PROC-01 / Required approvals | used | contextual |
| EV-bb40855a740b5ee5 | phase2:project-tasks / csv:row:95;task_id:TASK-094 | excluded | not_applicable |
| EV-bcbc0c503afbd0eb | phase2:project-tasks / csv:row:90;task_id:TASK-089 | excluded | not_applicable |
| EV-4605db9ffe9a395f | phase2:project-tasks / csv:row:56;task_id:TASK-055 | excluded | not_applicable |
| EV-cefdca50f7111d1f | phase2:POL-03 / Background | used | contextual |
| EV-6fe87a800f98737a | phase2:project-tasks / csv:row:47;task_id:TASK-046 | excluded | not_applicable |
| EV-a103372e47836fd6 | phase2:project-tasks / csv:row:40;task_id:TASK-039 | excluded | not_applicable |

## Verification and preserved work

- Full repository test suite: **356 passed**. Focused checks cover actual ingested passages,
  sentence-grounded quotations, paraphrases, 42-day equivalence, changed durations,
  negation, all-versus-standard scope, assignment-versus-signature clocks, target and date
  safeguards, unknown grammar versus empty retrieval, container record identity, graph/
  export disposition agreement, Streamlit result rendering and immutable assessment history.
- Ruff passes for the changed Python modules; `git diff --check` passes.
- Live browser inspection was attempted but the browser runtime reported no available
  browser. Streamlit's test harness verified result rendering and source-link/graph data;
  live click interaction and visual layout were not independently browser-verified.
- All three prior assessment rows (payload and result JSON) were checked unchanged after
  appending the new run. Existing staged and unstaged work was preserved; nothing was
  committed or pushed.

Original run: `RUN-93c0b22348c046db` (retained with its historical Insufficient result).
New automatic child: `RUN-cce80d955a6240e4`, review status **Not yet reviewed**.
Backup: `data/processed/evidence.before-onboarding-20260909T230038Z.sqlite3`.

Matching artifacts:
[HTML report](../reports/onboarding-assessment-20260909T230038Z/assessment.html),
[assessment JSON](../reports/onboarding-assessment-20260909T230038Z/assessment.json),
[graph JSON](../reports/onboarding-assessment-20260909T230038Z/graph.json),
[Graphviz DOT](../reports/onboarding-assessment-20260909T230038Z/graph.dot).

The classifier remains bounded rather than general semantic entailment. Unsupported
paraphrases can remain unclassified. The corpus snapshot is not a statement of present-day
policy validity, the bounded packet is not exhaustive, and undocumented dependence is
unknown. None of these limitations is presented as proof that source evidence is absent.
