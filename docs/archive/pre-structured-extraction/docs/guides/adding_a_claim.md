# Adding a claim

1. Start the app and open **Claims and Retrieval**.
2. Enter the original wording, subject, relationship, object, process, scope, conditions,
   applicable period, claim type, and development/held-out split.
3. Review the atomicity warning. If propositions could need different evidence or outcomes,
   use the split form; child claims preserve the original wording and parent ID.
4. Exclude unsuitable claims only with a reason. Do not tune rules using held-out claims.
5. Retrieve evidence, then have two people review independently before comparison.

Claims can also be created through `AtomicClaim` and `save_claim()`. Pydantic rejects unknown
fields, reversed periods, and exclusions without reasons.
