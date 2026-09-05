# Data dictionary

## Source

`source_id` is release-qualified; `original_file_path` locates the immutable input;
`checksum` is SHA-256. Dates distinguish creation from effective applicability. Version,
approval, lifecycle, predecessor/successor, derivation, and duplicate-group fields preserve
time and dependence. `metadata_provenance` states whether each value was direct, inferred,
or calculated. Excluded files retain an ingestion status and reason.

## Evidence

`evidence_id` is deterministically derived from source and locator. `locator` is a Markdown
heading/block path or CSV row plus record identifier. Text is verbatim Markdown content or
a faithful JSON representation of the structured row. Actor, role, process, system, dates,
version, extraction method, parent, provenance links, and structured metadata preserve
context without flattening important identifiers.

## Atomic claim

Claims record subject, predicate, object, process, scope, conditions, applicable period,
type, original text, atomicity status, ambiguity, development/held-out split, inclusion,
exclusion reason, and parent/child lineage. Held-out claims must not tune rules.

## Claim-evidence review

Each reviewer-specific link records one of support, contradict, qualify, contextual, or
not-applicable; four separate applicability dimensions; reason; confidence; notes; status;
and timestamps. Credibility records relevance, authority, directness, temporal validity,
independence, completeness, organisational applicability, formal/observed mode, limitations,
and justification. Values are contextual inputs, not objective truth probabilities.

## Assessment and adjudication

A claim assessment stores one four-way outcome, separate categorical confidence,
uncertainty explanation, explanation, reviewer, status, and time. Automated assessments
have ordered rule traces. Adjudications identify both human reviewers and either record a
resolved reference outcome or preserve genuine disagreement without one.

## Retrieval, evaluation, and audit

Retrieval runs store claim, method, query, configuration, model/version, latency, timestamp,
rank, and component scores. Evaluation errors use the documented taxonomy and retain claim,
component, evidence identifiers, reviewer, status, and description. Audit events append
actor, action, entity, changed fields, and timestamp.
