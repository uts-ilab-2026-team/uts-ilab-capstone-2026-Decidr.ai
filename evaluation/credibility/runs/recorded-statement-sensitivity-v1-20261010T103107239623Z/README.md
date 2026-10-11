# Recorded-statement scoring development checkpoint

Status: experimental; not promoted to production.

Repository revision at execution: `70cc85560ea78658415c71d379298c185c606c66`.

## Purpose

Compare the production formula with a candidate that removes the outer
authority multiplier only for eligible recorded-statement assessments.
Authority remains a weighted dimension. The candidate requires maximum
supplied directness, specificity and completeness.

## Observed results

- Cases: 8.
- Changed overall outcomes: 4.
- Candidate cases retained without admitted edges: 4.
- Four narrow recorded-statement claims changed from Insufficient to Supported.
- Four broader claims remained Insufficient under supplied target mismatches.

## Interpretation limits

Targets, source classes, support attempts and quality judgements were supplied.
Broader cases deliberately attempted support to exercise target rejection.
They were not automatically interpreted or independently adjudicated.

The result demonstrates conditional scoring and admission behaviour.
It does not measure interpretation accuracy, calibration, generalisation
or Phase 3 readiness. Scores are not probabilities.

Production scoring, database contents and frontend behaviour were unchanged.
No model was called.

## Reproducibility

The folder contains frozen inputs, provisional references, configuration,
baseline/candidate responses, runner source and execution metadata.
`run.json` records code/configuration hashes and the repository revision.

## Review needed before promotion

Review target, stance, scope, attribution and provenance independently.
Include conflicting accounts, incomplete context and uncertain attribution.
Citation-integrity failures should be tested separately from semantic errors.
Do not tune further on these eight examples or treat provisional labels
as independent ground truth.
