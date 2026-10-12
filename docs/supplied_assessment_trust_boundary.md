# Supplied assessment trust boundary

Audited against feat/corpus-retrieval-integration at 70cc855.
The additional assurance fields describe existing behaviour; they do not change
admission, weights, confidence calculations, or verdict rules.

## What the endpoint checks

POST /api/corpus/assess-supplied requires the existing authentication dependency.
It resolves evidence and source identities from the configured read-only corpus
index, checks exact quotation spans and locators, and validates request types,
configured scoring keys, dates, target declarations and origin consistency.
Stored lifecycle/date constraints and documented source dependence still apply.
The caller cannot replace stored source objects or the server configuration.

## What remains supplied

The caller supplies stance, mode, target, scope/time matches, authority judgement,
source class, approval scoring key, origin and independence declarations, and
directness/specificity/completeness scores. A nonblank explanation is not proof.
An independence declaration is checked for consistency, not independently
established by the service. Authentication does not establish expertise or review.

A valid citation may therefore accompany an incorrect relationship. In the
adversarial HTTP test, a caller marks "Written approval is required." as support
for "Written approval is never required." The endpoint calculates Supported
under that supplied relationship. This is a documented interpretation boundary,
not measured semantic accuracy.

Stored source metadata and supplied scoring categories remain separate in the
response. No automatic source-type-to-scoring-class reconciliation is performed.
The API cannot certify the caller's approval key merely because it is configured.

## Response contract

The additive top-level assurance object makes these boundaries machine-readable.
Every verdict and confidence is conditional_on_supplied_judgements.
Exact citation checks, semantic verification, authority, independence, quality,
source-class/approval assumptions, and review status are separately disclosed.
The existing input dispositions retain exact citations and supplied judgements,
including rejected qualifications and unresolved inputs.

Clients must retain this envelope alongside the nested assessment. Display the
conditional nature of verdict/confidence wherever those results are shown.
Do not label authority_verified or independence_verified as service verification;
these names record supplied declarations. Do not infer human review from a
successful request. The endpoint does not persist review or assessment history.

This disclosure is not an authorization gate. Any user admitted by the existing
authentication dependency can submit judgements. Restricting who may publish
reviewed findings requires a separate review/authorization design.

## Verification

Focused API/response tests cover false semantic assertions with exact citations,
caller categories distinct from stored metadata, retained quality assumptions,
attempted assurance/status injection, and responses with no admitted evidence.
Existing tests cover authentication, forged citations, dates and target gates.
No model, live corpus, saved graph or frontend was changed during this audit.
