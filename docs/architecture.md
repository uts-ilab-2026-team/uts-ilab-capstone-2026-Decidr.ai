# Current architecture

Current metadata ingestion uses `ingestion-v3-document-metadata`. See the
[source metadata correction](source_metadata_correction.md) for document-scoped approval,
exact header provenance, separate update/supersession dates, unresolved conflicts and the
fixed-output development replay. The bounded classifier remains unchanged; both experimental
alternatives remain disabled. Existing ledger/snapshot artifacts were not migrated.

The employee path is:

`read-only Phase 2 corpus → registration/extraction → SQLite evidence ledger → bounded claim
intake → lexical retrieval/provenance expansion → automatic evidence classification →
deterministic applicability/credibility reasoning → immutable assessment → explanation,
source inspection, graph and export → optional human correction in a new snapshot`

SQLite is authoritative for saved provenance, application assessments and separately stored
human judgements. NetworkX graphs are derived inspection views. The production classifier
is `automatic_evidence.py` (`bounded-evidence-5`), not the question interpreter or Approach B
scenario comparator. A resolved claim can receive a provisional result with incomplete
classification; unresolved claim meaning remains pending clarification.

`claim_workflow.py` freezes the claim, candidate packet, source graph, ledger revision and
as-of date. `assessment_snapshot.py` derives and persists target-specific findings, coverage,
cited actions and ordered presentation sections. `conversation.py`, `app/employee.py`,
`claim_graph.py` and `claim_export.py` consume that result. A read-only adapter presents old
snapshots without changing their verdict. New runs record creation time separately from
the period assessed. Source links inspect captured text, even after the live ledger changes.

The reasoner separates policy, practice and record targets; checks scope, conditions, dates,
versions and documented dependence; then applies the existing four outcomes and qualitative
confidence. A source's owner is not automatically its decision authority. A recorded claim
is not automatically an established real-world event. Context, missingness, classification
failure and bounded retrieval remain distinguishable.

Research blind review/adjudication uses separate tables and evaluation gates. Application
review cannot manufacture independent reference judgements. Phase 1 remains framework
material; Phase 2 is modelling evidence; held-out/Phase 3 references are not runtime evidence
or development labels. Corpus revisions and source checksums remain explicit.

The [experimental structured-extraction path](structured_extraction_experiment.md) is a
standalone module and local runner. It proposes separately cited components, validates exact
spans, compares only bounded component relations, and uses the same deterministic reasoner
in an isolated diagnostic. Its detached graph overlay reifies *sourced assertions* with
component citations, rather than adding role-authority fact edges. It never writes the
working ledger or enables a new employee path. Span validity is not semantic validation.

See [current usage](claim_first.md), [known limits](known_limitations.md) and the
[documentation inventory](documentation_inventory.md). The previous architecture description
is [archived](archive/pre-structured-extraction/docs/architecture.md).
