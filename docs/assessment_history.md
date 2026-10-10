# Saved supplied assessments

Assessment history is an optional backend capability. It preserves conditional
supplied-judgement results without changing the frontend, interpretation proposals,
corpus database or saved organisational graph.

## Configuration

Set `DECIDR_ASSESSMENT_DB` to a dedicated SQLite file before starting the API:

```bash
export DECIDR_ASSESSMENT_DB="$HOME/Downloads/Decidr-local/assessment-history.sqlite"
```

Keep the existing authentication and `DECIDR_CORPUS_DB` configuration. The history
file must differ from the corpus and authentication databases, including symlinks
and hardlinks. It is created on the first successful save. An existing unrelated
database is rejected. Unconfigured history returns HTTP 503. Read requests do not
create a database.

## API contract

All routes require the existing authenticated user. Ownership comes from the
session, never from a request field. Other users' snapshots return HTTP 404.

| Method | Route | Behaviour |
| --- | --- | --- |
| POST | `/api/assessments` | Assess supplied inputs and explicitly save a snapshot |
| GET | `/api/assessments?limit=20&offset=0` | List the user's saved summaries |
| GET | `/api/assessments/{run_id}` | Reopen the frozen snapshot |
| GET | `/api/assessments/{run_id}/export` | Download the same snapshot as JSON |

The POST body wraps the existing `/api/corpus/assess-supplied` request:

```json
{
  "request_id": "unique-save-request-001",
  "assessment": {
    "...": "Use the complete existing SuppliedAssessmentRequest here"
  },
  "parent_run_id": null,
  "revision_reason": null
}
```

The abbreviated assessment above illustrates the envelope; it is not a runnable
assessment payload. Use validated claim, facet, target, date, citations and supplied
judgements from the existing endpoint contract. Client verdicts, ownership fields
and claims of human review are rejected.

A new save returns HTTP 201 and `{snapshot, snapshot_sha256}`. Repeating an identical
validated body with the same `request_id` returns the same snapshot with HTTP 200,
even if the corpus later becomes unavailable. Reusing that identifier with different
inputs returns HTTP 409. Use a new identifier for each intended reassessment.

Saving runs the assessment on the current indexed evidence and configuration. It
does not accept a client-generated verdict and does not guarantee the result equals
an earlier preview if its dependencies have changed. The original preview endpoint
continues to return an unsaved result.

## Frozen content and revisions

Each snapshot contains the validated inputs, server-generated response, exact cited
passages, cited source metadata, full scoring configuration, timestamp, owner and
run identifiers. Qualifying and excluded evidence, limitations, reasoning traces
and supplied-judgement disclosures remain present. Human review remains
`not_established`; saving does not promote the record into a verified fact.

Revisions use a new request identifier, the existing `parent_run_id`, and a nonblank
`revision_reason`. Claim text, facet and target must match the parent. Changes to
judgements, assessment date, corpus or configuration create a child snapshot with
the parent's hash; they never replace the parent. Revisions use the current corpus
and configuration at save time. Correction against the parent's frozen corpus is
not implemented.

GET and export read the stored snapshot without rerunning retrieval or scoring.
They remain available when the corpus or assessment configuration is unavailable.
Only cited evidence is frozen, not the entire corpus. The full index payload hash
identifies the indexed source/evidence revision; it is distinct from the raw-corpus
ingestion fingerprint. Source-file hashes record files on disk and runtime versions,
not a signed identity of loaded executable code.

## Integrity and limits

SQLite transactions, unique owner/request identifiers and append-only triggers
protect normal application writes, retries and parent links. There are no update
or deletion endpoints. Stored hashes are verified on read. These hashes detect
accidental corruption; a privileged database administrator can bypass triggers and
recalculate hashes. Keep database backups and filesystem permissions appropriate
to the evidence stored.

This is owner-scoped history, not shared team review or a facts-register publishing
workflow. It has no new frontend controls, automatic save, LLM calls or automatic
human-review attribution. Credibility scores remain conditional on supplied inputs.

## Verification

`tests/test_assessment_history_api.py` covers save/reopen/export, unavailable corpus,
parent preservation, invalid revisions, exact retries, concurrent retries, owner
isolation, authentication, target database separation, citation failures, corruption
and rejection of client-supplied verdicts. Existing supplied-assessment tests verify
the preview contract remains intact.
