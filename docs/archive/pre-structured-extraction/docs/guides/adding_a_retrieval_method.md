# Adding a retrieval method

1. Accept the same validated `AtomicClaim` and ledger evidence units used by existing methods.
2. Return evidence ID, source ID, locator, text, rank, method score, and an interpretable
   provenance explanation.
3. Persist method configuration, model/version where relevant, latency, ranks, and component
   scores through `save_retrieval_run()`.
4. Never bypass reviewer applicability or silently download a model/service dependency.
5. Evaluate on the same adjudicated pools and report per-claim misses and irrelevant results.
6. Add challenge tests for scope, role, temporal, duplicate, and supersession behavior.
7. Do not recommend retention until observed benefit, errors, processing cost, maintenance,
   and reviewer effort have actually been compared.
