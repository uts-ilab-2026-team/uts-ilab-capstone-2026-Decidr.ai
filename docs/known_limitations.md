# Known limitations and validation boundaries

The classifier remains `bounded-evidence-5`; ingestion and metadata constraints now use the
[document-scoped correction](source_metadata_correction.md). The earlier development comparison found
11/46 relationships classified and 9 matching provisional expectations. The direct local
model baseline classified 41/46 after quote validation and matched 29. These are small,
purposive, author-annotated development comparisons, not independently validated accuracy.

The [structured-extraction experiment](structured_extraction_experiment.md) reports component
correctness, relationship errors, downstream diagnostic verdicts and graph expansion
separately. Its candidate is not enabled. The first joint-request pilot leaked source details
into the submitted claim; the second transport separates claim and source requests physically.
That change prevents direct source access during claim extraction, but does not establish
that its normalisations are correct. The completed candidate classifies only 3/62 development
relationships, with zero matches to provisional labels; 59 cases have rejected components.
The direct-model comparison classifies 56/62 and matches 40, but includes 13 serious polarity
or false-decisive relationship errors. Neither alternative supports production replacement.

- A verbatim quotation establishes provenance only. Actor/action identity, authority status,
  negation scope, target, quantifier, conditions, exceptions and event identity can still be
  wrong. Extracted assertions are never stored as established facts by the candidate.
- Explicit unassignment differs from missing documentation; informal practice differs from
  formal authority. Even a source asserting approval does not prove approval occurred.
- Normalised strings are model proposals. Equal strings permit deterministic comparison
  conditional on extraction, not a claim of verified real-world entity/event identity.
- Unknowns remain null. An unspecified percentage denominator, actor or effective date
  cannot be filled from the desired verdict. Last-updated and creation dates are not effective
  dates. Source existence by a date does not establish continuing practice at that date.
- The separated candidate extracts at most one focused assertion per evidence unit. Other
  assertions, cross-sentence conflicts and missing exception coverage may remain unextracted.
  This is disclosed as bounded extraction, not complete evidence interpretation.
- Frozen and fresh development annotations require independent adjudication. Partial component
  annotations do not cover every returned field. Normalisation disagreements are reported
  separately from categorical errors where possible; no human validation is claimed.
- The original experiment's frozen metadata misattributes the support procedure's approval
  and omits the old discount policy's superseded date. A separate corrected dataset fixes
  those inputs without rewriting labels or model outputs. Applicability agreement improves
  56→62/62 against provisional labels, but the supersession day remains unknown and PROC-05
  still lacks an effective start. The original scores remain research history. Header parsing
  does not reconcile arbitrary body prose; unresolved conflicts need research adjudication.
- Downstream candidate scores use a designated single passage and fixed credibility assumptions
  through the existing reasoner. They do not establish full-packet deployment performance.
  Non-applicable dates can mask a serious relationship error, so verdict accuracy alone is unsafe.
- Retrieval comparison uses known designated passages, not complete adjudicated relevance pools.
  All 62 were already found by lexical top-20. Graph additions have no demonstrated recovery
  gain on this matrix; unjudged additions are not automatically relevant or irrelevant.
- At the production 50/50 cap, graph expansion adds nothing when lexical retrieval fills the
  packet. This is observed behaviour, not evidence that graph expansion never helps elsewhere.
- Assertion-graph overlays are detached proposals with exact component citations. They must not
  be traversed as established authority/entity facts. Their integration representation is
  implemented; learned assertion-edge retrieval has not been evaluated or enabled.
- Workflow tests and Streamlit structure checks do not prove semantic quality. Live browser
  layout/click/print verification was unavailable during the earlier presentation work.

Automatic assessment still precedes optional review. Clarification may be needed for unresolved
claim meaning. Human corrections create new snapshots; reviewer names are audit identifiers,
not authentication. Submitted study records and historical verdicts are preserved. No held-out
claims were used for this experiment and no independent research reference was manufactured.
