# Candidate claim portfolio for human approval

Reviewer identities are stored once in `configs/human_study.json`. None of these claims,
evidence hints, or split assignments is an adjudicated reference, human label, or final
research decision.

The reviewable source is `framework/candidate_claim_portfolio.csv`. It contains eight atomic
candidates grounded in the complete Phase 2 corpus and cross-checked against the illustrative
four-row Phase 1 `labelled_claims_sample.csv`. Where sample wording bundled propositions or
did not exactly match policy language, the candidate was narrowed or corrected and the
change is recorded.

## Proposed split

- Development: CAND-01, CAND-02, CAND-03, CAND-05, CAND-06, CAND-07.
- Held-out: CAND-04 and CAND-08.

CAND-04 directly tests routine ticket-before-escalation practice using timestamped and
testimonial evidence; prescribed PROC-05 is contextual rather than the claim target. CAND-08
tests whether one specific `2026-02-18` deployment received the expected sign-off. Their
incomplete and conflicting operational trails make them useful challenge cases without
exposing an expected interpretation to blind reviewers.

## Approval procedure

1. The team reviews claim definitions and verification status in the portfolio CSV, and
   separately reviews rationale, evidence hints, and split in the design CSV.
2. Amend or reject candidates; record a reason for material changes.
3. Confirm atomicity and the final development/held-out assignment.
4. Only after explicit approval should candidates be entered or promoted into the claim
   register.
5. Generate separate blind packets for Royston and Isanka. Evidence hints in this proposal
   are portfolio-design aids and should not be copied into blind human outcome judgements.
6. Do not run final evaluation until both independent reviews and adjudication are complete.
