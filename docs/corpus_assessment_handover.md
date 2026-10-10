# Corpus retrieval and supplied assessment handover

Implementation baseline: `9236c1e` on `feat/corpus-retrieval-integration`.

## Current capability

The frontend retrieves corpus evidence for the submitted claim and opens exact
citations. A separate authenticated backend endpoint assesses explicitly supplied
interpretations through the existing graph credibility framework.

Automatic interpretation is unfinished. The supplied-assessment endpoint does
not infer evidence relationships, perform retrieval, or establish that supplied
judgements are semantically correct. It does not create human review records.

The checked local Phase 2 index contains 45 sources and 796 evidence units.
The database is local and is not included in the Git branch.

## Endpoints

All three routes require the application's existing authentication.

| Route | Purpose |
| --- | --- |
| POST `/api/corpus/search` | Retrieve unassessed candidates for an exact claim |
| GET `/api/corpus/evidence/{evidence_id}?source_id=...` | Resolve a citation against the current index |
| POST `/api/corpus/assess-supplied` | Assess supplied interpretations for one facet |

Configure `DECIDR_CORPUS_DB` with the path to an existing corpus SQLite database.
Corpus access through these routes is read-only. Restart the backend after
updating its code or environment configuration.

The supplied-assessment route is not connected to the frontend.

## Supplied-assessment request

The top-level JSON object contains:

| Field | Contract |
| --- | --- |
| `claim_text` | Original claim, preserved without trimming |
| `facet` | The specific assertion being assessed |
| `as_of` | Explicit assessment date in YYYY-MM-DD format |
| `inputs` | Between 1 and 50 supplied interpretations |

Each input requires:

| Field | Contract |
| --- | --- |
| `stance` | `support`, `contradict`, `qualify`, `context`, or `unresolved` |
| `mode` | `formal`, `observed`, or `unresolved` |
| `rationale` | Explanation of the supplied interpretation |
| `citations` | Between 1 and 20 exact spans, all from one source |
| `origin_id` | Supplied dependence/origin grouping |
| `source_class` | Existing key in the credibility configuration |
| `approval_key` | Existing key in the approval configuration |
| `scope_matches` | Boolean or null for unresolved |
| `temporal_matches` | Boolean or null for unresolved |
| `authority_verified` | Boolean or null for unresolved |
| `directness` | Finite number from 0 to 1 |
| `specificity` | Finite number from 0 to 1 |
| `completeness` | Finite number from 0 to 1 |
| `judgement_basis` | Basis for the supplied applicability and quality judgements |
| `origin_basis` | Basis for grouping dependent evidence |

Each citation requires `evidence_id`, `source_id`, `locator`, `quotation`,
`start`, and `end`. Offsets are Python string indices: start inclusive and end
exclusive. The quotation must exactly match the stored passage at those offsets.

Obtain evidence identities, locators and text from corpus retrieval or citation
lookup. Do not invent identifiers or alter quotations.

Clients cannot supply replacement Source objects. The endpoint loads source
metadata and cited passages from SQLite within a read transaction. Source class,
approval key, authority, quality and origin grouping remain supplied judgements;
citation validation does not independently establish them.

Request strings are bounded and must not be blank. Unexpected fields are
rejected. The route constructs every interpretation using the submitted claim
and facet, preserving their exact text.

## Response and display contract

The response includes:

- `schema_version`: `facet-assessment-response-v1`
- `status`: `assessed_supplied_judgements`
- `assessment_scope`: `facet`
- `interpretation_basis`: `supplied_judgements`
- Original `claim_text`, `facet`, and `as_of`
- `assessment`: formal, observed and overall outcomes, confidence, evidence,
  dimension scores, gaps and rule trace
- `inputs`: every supplied interpretation, exact citations, stored source
  metadata, supplied judgements, edge ID, admission flag and reasons
- `limitations`, `config_version`, `index_scope: current`, and `persisted: false`

Consumers must retain both `assessment` and `inputs`. Qualifications, context
and unresolved interpretations can remain in `inputs` without becoming decisive
graph edges. Returning only `assessment` would hide those records.

`admitted_to_framework` means an edge entered the framework. It does not mean
the edge was material or independently determined the verdict. Materiality and
dependence decisions remain in the assessment evidence and trace.

The four framework outcomes are Supported, Contradicted, Contested and
Insufficient evidence. `qualify` is an evidence relationship, not a fifth verdict.

Scores are configured framework scores, not probabilities of truth.
A formal-rule finding does not establish compliance in practice. A missing
observed attestation in this packet is not proof of a corpus-wide evidence gap.

This endpoint returns an assessment for one facet. Consumers must not promote
it to a whole-claim verdict without an explicit aggregation design.

## Error handling

| Status | Meaning |
| --- | --- |
| 401 | Unauthenticated request, as checked by the existing auth dependency |
| 404 | Cited evidence/source pair absent from the current index |
| 422 | Invalid request, quotation/locator mismatch, or invalid supplied judgements |
| 503 | Missing/unreadable corpus index or unavailable assessment configuration |

Do not turn these errors into an evidence verdict.

## Verification completed

At the implementation baseline:

- 416 tests passed locally.
- Repository and graph formatting checks, and lint checks, passed locally.
- Endpoint tests covered authentication, unchanged database bytes, citation
  mismatches, invalid judgements, explicit dates and retained qualifications.
- A temporary HTTP test using actual Phase 2 policy and interview passages
  returned 200, retained both citations and left the corpus database unchanged.

The real-corpus HTTP check used an isolated test application and a test identity.
It did not verify browser login or live frontend assessment integration.
Development relationships and quality values were supplied by the test script;
these checks do not establish interpretation accuracy or Phase 3 readiness.

Run the relevant tests in your configured project environment:

```bash
python -m pytest tests/test_assessment_adapter.py tests/test_assessment_response.py tests/test_supplied_assessment_api.py -q
```

## Code ownership and next work

| Area | Entry point |
| --- | --- |
| Retrieval and section grouping | `decidr/hybrid.py::search_corpus` |
| Interpretation and citation contract | `decidr/interpretation_models.py` |
| Applicability gates and graph adapter | `decidr/assessment_adapter.py` |
| Complete JSON response | `decidr/assessment_response.py` |
| Supplied-assessment HTTP route | `decidr/api/supplied_assessment.py` |
| Credibility configuration | `framework/data/credibility.json` |

The remaining interpretation work must produce claim-specific relationships and
explicit scope, date, authority and dependence judgements. Unsupported comparisons
must remain unresolved. Retrieval rank must never substitute for a relationship.

Local LLM experiments have not produced a validated production interpreter.
No model is called by the supplied-assessment route. Proposed development
references remain provisional and must not be described as independent ground truth.

The adapter currently groups origins at source level, conservatively treating
different rows from one source together. It does not resolve person-role authority.
Results are not saved as immutable assessment history, and the response does not
contain a complete reproducibility manifest or frozen corpus revision.

Frontend assessment integration is deferred. When undertaken, it must preserve
qualifications, excluded inputs and limitations, and clearly distinguish supplied
judgements from automatic classification and human review.
