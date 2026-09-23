# Credibility framework and facts register

## Purpose

The implementation follows the project's ledger-first, reviewer-led methodology. The
credibility framework assesses how useful one evidence item is for one atomic claim. The
facts register is a derived view over the relational evidence ledger; it does not create a
second source of truth.

## Credibility framework

`decidr.credibility.CredibilityFramework` applies two ordered stages:

1. The applicability gate checks target, scope, conditions, and time. A failed item is
   excluded before scoring.
2. An applicable item is reviewed for relevance, institutional authority, directness,
   temporal validity, independence, completeness, and organisational applicability.

The configurable weighted average is a materiality score, not a probability of truth. The
default threshold is 0.50. Items below the threshold remain in the audit record but are not
decisive. Claim outcome and confidence are calculated separately by the deterministic
reasoning engine.

## Facts register

`decidr.facts_register.FactsRegister` projects existing claims, reviewer assessments,
evidence counts, gaps, and adjudications into these visible states:

- Candidate
- Review in progress
- Reviewed - awaiting adjudication
- Assessed organisational finding
- Unresolved reviewer disagreement
- Excluded

Only a resolved adjudication creates an assessed organisational finding. A single human
review, an automated result, or an unresolved disagreement remains clearly labelled and
cannot silently become a fact.

The Streamlit application provides separate **Credibility Framework** and **Facts Register**
pages. The facts register can be downloaded as CSV or JSON.

