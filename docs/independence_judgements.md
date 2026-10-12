# Explicit independence judgements

Independence policy v2 changes new calculations, including calculations from legacy
graphs. Saved results are not rewritten. Missing declarations default to unverified;
old source IDs and duplicate-group labels are not retrospectively certified.

FORMAL/OBSERVED edges and supplied-assessment inputs accept:

- `independence_verified`: strict boolean, default false.
- `independence_basis`: explanation, required and nonblank when verified is true.

True is a caller-supplied judgement that this origin is established as independent
of other credited origins in the relevant claim/facet packet and lane. It is not
an automatic verification, authentication of a reviewer, or proof of factual truth.
The basis should identify the provenance evidence and comparisons supporting it.
Reassess this judgement when the packet changes. Different identifiers alone are
not a sufficient basis. Copies can carry the same established origin; they still
count once. False covers unestablished independence, not proven dependence.

Corroboration bonuses require established distinct origins. Unknown-origin items
retain the baseline corroboration value and cannot borrow a bonus from other
items. Source quality and transmission quality are not automatically penalised.
The existing source_independence dimension remains neutral (1.0); independence
is enforced through aggregation and the explicit trace, not a new numeric penalty.

For each lane and stance, the combined weight is the greater of:

1. The sum of the strongest material assessment per established origin.
2. The strongest single material assessment across all origins.

Unknown-origin items therefore remain usable alone, but do not accumulate votes
or add a vote on top of the established total. This is a conservative decision
rule, not an assertion that unknown sources are duplicates. Supporting and opposing
accounts remain separate. Higher confidence requires at least two established
origins as well as the existing confidence conditions.

Within a claim and lane, conflicting or missing independence declarations for the
same origin prevent that origin receiving additive credit. This conservative rule
also considers retained graph attestations that are not applicable. Non-admitted
adapter inputs remain in the response but do not become graph attestations.

Documented duplicate/derivation constraints in the adapter remain in force. Version
1 source-level origin grouping remains conservative for separate rows or messages
within a file. No person-to-person chain is inferred from wording, names or IDs.
The new judgements and their basis are preserved in supplied-assessment responses;
core traces describe the policy and effective group status.

Tests use explicitly stipulated synthetic independence, not corpus adjudication.
Existing historical/dependence fixtures now declare that assumption so those tests
continue to test temporal behaviour and origin caps. Numeric credibility weights,
materiality thresholds, source metadata and stored graph data are unchanged.
