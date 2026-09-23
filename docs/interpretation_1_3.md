> **Status: archived instructions / research history.** Archived interpretation-1.3 experiment. Its development findings remain historical evidence, not production guidance.
> Use [current employee guidance](claim_first.md), [architecture](architecture.md) and the
> [documentation inventory](documentation_inventory.md). The original body below is retained.

# Interpretation 1.3 development note

Interpretation 1.3 represents an employee question as a query frame rather than a factual
claim. It separates the question operator, modality, business action, business object,
known actor, requested fields, and null answer slots. Requested answers remain unknown until
retrieval and do not count as missing interpretation input. `QueryFrame` becomes an
`AtomicClaim` only through the explicit post-retrieval conversion layer after a candidate
value has an exact supporting evidence span.

The runtime schema uses these structural fields:

- `query_operator`
- `business_action`
- `business_object`
- `known_actor`
- `requested_fields`
- `answer_slots`
- `modality`
- `process`
- `assessment_target`
- `conditions`
- `temporal_scope`

The deterministic structural normaliser applies domain-independent English transformations.
It separates modal auxiliaries and question operators from business actions, converts bounded
passive constructions to active lemmas, takes a purpose infinitive as the action underlying a
procedure question, and inherits one unambiguous shared process into another compound fragment.
Every transformation records its input fields, output fields, supporting employee wording, and
whether protected meaning changed. It never rewrites explicit quantities, dates, negation,
modality, actors, or named entities.

Assessment-target arbitration reads the complete question. Formal requirements, approved
procedures, obligations, and permissions indicate `prescribed_rule`; descriptions of normal or
actual behaviour indicate `actual_practice`; database, CRM, audit-log, and system-record content
indicates `recorded_state`. Conflicting explicit signals remain `unknown` and require employee
confirmation.

One targeted repair may follow a critical validation failure. Its request contains only the
affected frame, invalid fields, field-specific messages, locked validated fields, relevant
question spans, and schema definitions. Its response contains only corrected fields and their
supporting spans. The merge rejects changes outside the invalid field set, changes to locked
fields, spans for unchanged fields, and removal of protected employee meaning. The merged frame
then passes through the complete schema, grounding, and semantic validators.

If repair fails, technical provenance records the fallback parser version, its generated query
frame, the legacy parser proposal, the selection reason, unresolved fields, and the mandatory
employee-confirmation flag.

The saved interpretation-1.2 development outputs were re-scored offline without model calls.
Raw model semantic acceptance remained 8/12. Generic deterministic structural normalisation
accepted 12/12, with 0/12 requiring targeted repair and 0/12 requiring fallback. This is a
normalisation result, not an improvement in model accuracy. The four prior failure categories
were corrected by requested-answer semantics, passive/modal separation with compound-context
inheritance, purpose-infinitive action extraction, and complete-question target arbitration.

The 1.3 interpreter remains experimental. The Streamlit query-frame UI is not promoted, and the
LLM remains outside evidence relationships, credibility, verdict, and confidence calculation.
