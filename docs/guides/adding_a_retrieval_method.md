# Adding a retrieval method

1. Accept the same validated `AtomicClaim` and ledger evidence units used by existing methods.
2. Return evidence ID, source ID, locator, text, rank, method score, and an interpretable
   provenance explanation.
3. Persist method configuration, model/version where relevant, latency, ranks, and component
   scores through `save_retrieval_run()`.
4. Never bypass applicability checks or claim semantic relationships from retrieval scores or silently download a model/service dependency.
5. Evaluate on the same adjudicated pools and report per-claim misses and irrelevant results.
6. Add challenge tests for scope, role, temporal, duplicate, and supersession behavior.
7. Do not recommend retention until observed benefit, errors, processing cost, maintenance,
   and reviewer effort have actually been compared.

For development comparisons, report designated-passage recovery and unjudged additions
when complete adjudicated pools are unavailable. Compare graph expansion against equal-budget
lexical retrieval. Current measurements are linked from [the experiment](../structured_extraction_experiment.md).
