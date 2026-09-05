# Human review and adjudication protocol

1. The research team selects six-to-ten corpus-grounded claims and records why each was
   included. At least two challenge cases are held out before rule tuning.
2. A reviewer confirms every claim is atomic, scoped, conditioned, and time bounded. Compound
   wording is split while retaining the original text.
3. Two distinct humans receive separate blind packets. They do not see automated outcomes or
   each other's evidence links, credibility values, outcomes, confidence, or explanations.
4. Each reviewer retrieves and locates evidence, checks target/scope/conditions/time, assigns
   one relationship, records credibility dimensions with justification, chooses a four-way
   outcome, and explains uncertainty separately.
5. Only after both reviews are complete does comparison begin. Differences are inspected at
   evidence and claim level. An adjudicator either records a final reviewed reference or
   explicitly preserves genuine disagreement.
6. Development claims may inform documented configuration choices. Held-out claims must not.
7. Evaluation is run only after adjudication. Incomplete evidence pools receive descriptive
   counts rather than precision/recall/F1. Small-sample limitations accompany every result.

The application never fabricates a missing reviewer, label, link, adjudication, or result.
