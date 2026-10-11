# Prototype walkthrough

1. Choose **Check a claim** and enter a claim in your own words. Supply an optional scope clarification if offered; the submitted claim remains visible unchanged.
2. Choose an assessment date and **Assess claim and save result**. The result shows the formal and observed-practice outcomes separately, plus conditional confidence and the evidence considered.
3. Open an evidence row or a node in **Evidence graph**. Use Formal, Practice or Both to inspect the lanes. Relationships and materiality come from this assessment, not from a fixed demonstration claim.
4. Inspect the source's exact quotations, dates, credibility dimensions, derivation, authority checks and recorded lineage. A missing score means the input was not admitted; it is still available for review.
5. Use **Review this result** to explain any changed judgement and save a separate revision. This is available immediately and after reopening a saved assessment from Dashboard. A review is a conditional human judgement, not independent authentication.
6. Export the saved JSON for the audit record. **Run again** returns to claim assessment so that a new result can be created. Previous results remain unchanged.

## Honest showcase boundaries

Automatic interpretation supports the implemented approval-rule grammar. Thresholds and sources come from the submitted claim and corpus; there is no universal 15% threshold or fixed four-claim result table. Unsupported wording, uncertain authority, incomplete dates and insufficient evidence may remain unresolved. Equivalent percentage spellings, formatted currency amounts, ampersand/and role wording, and expense rules phrased “need approval from” or “must be approved by” are supported. Missing conditions and unsupported compound claims are not filled in.

The reference PDFs illustrate presentation; their example verdicts, materiality values and named actors are not copied into automatic results. No actor/authority links are invented for the graph. Lineage displays only identifiers recorded in the saved source metadata. Independent corroboration is not inferred from copies or related records.

The separate **Register results (recalculated)** view displays the existing curated register. It is distinct from the immutable automatic-assessment history. Search and counts on the saved dashboard apply to the current page.

No paid model or new external service is needed. Before presenting, verify the browser flow with your local corpus: create a result, open graph and source details, return, reopen it from Dashboard and export it. A deliberately unsupported claim should remain unresolved rather than receive a fabricated verdict.

## Final local fixes

- A visible **View evidence graph** button jumps from the outcome to the graph. The graph uses connected branches, removes empty lanes and includes a separate unresolved lane when needed. Every card identifies its passage and includes a quotation preview.
- Evidence-gap explanations distinguish evidence that was examined but excluded from an empty assessment. Raw framework gap messages remain in technical details and exported snapshots.
- Automatic differences name the fields that failed comparison; unsupported surrounding conditions are explained separately. Original claims and quotation offsets are unchanged.
- Saving a review checks the returned parent, claim, facet, date and saved status before displaying it as the new revision.

Reopen saved results to see presentation changes. Use **Run again** to apply updated interpretation to a new snapshot; old assessments intentionally keep their old results.

## Date, role and operational checks

Choose **Assess as of** on the claim form. This sets the assessment date; it does not supply missing dates in sources. The source detail role/person cross-check searches corpus passages and retains exact citations; matching a name or title does not verify adoption authority.

New assessments also show **Recorded practice compared with the requirement**. Supported expense and discount rules are compared with structured records from the frozen corpus snapshot, using the claim's own threshold, currency, role, scope and timing. Explicit late approvals can be recorded departures. Empty approval fields are documentation gaps, and task completion is not a reimbursement date. Reported alternative routing remains a report requiring review. Conflicting fields remain unresolved.

These event comparisons are separate from the formal-rule verdict: breaking a policy does not establish that the policy does not exist. They do not supply missing authority or independent corroboration. Unstructured interview and message interpretation remains limited. Run again to create a new snapshot with these checks; existing snapshots are preserved.

## Identified transaction claims

Claims such as “SALE-972 Alex approved 32% discount before the contract was signed” use the supplied identifier to retrieve the record and explicit references. Unrelated keyword matches are omitted; unknown identifiers do not fall back to unrelated results. The identifiers, people and percentages are extracted from the claim, not mapped to fixed answers.

For supported approval-event wording, a component comparison shows the recorded discount, named approval and before-signing timing separately. Explicit linked records can supply missing facts. Conflicting values are shown, another approver does not prove the claimed person never approved, and same-day or CRM close dates do not prove approval before signing. The comparison is saved with exact citations; source credibility and authority remain separate checks. Unsupported event wording still requires review.

## Connected formal, observed and documented evidence

For approval claims mentioning discounts or expense claims, new assessments scan the frozen corpus for subject-specific policy and process passages, reported accounts, qualifying structured records, role headings and explicitly referenced communications. The **Connected evidence** section is inside **View evidence graph**. Its three categories retain exact quotations. Select a passage to inspect its limitations and navigate its actual record/person connections. Shared-topic connections are labelled as context, not corroboration.

The comparison flags a recorded approver whose documented role differs from a candidate policy requirement, but does not infer missing Finance approval, exclusive authority, delegation or an exception. Approval referenced outside CRM is a documentation finding, not proof no approval occurred. The original Slack message must be present and explicitly linked to be displayed as direct evidence. Interview accounts are retained as reports; broad semantic contradiction classification is not implemented.

Source dates, passage dates and dated message headers exclude later evidence. Missing dates remain explicit limitations. A February 2026 assessment will not include June 2026 interviews. The complete connection report is frozen with the saved assessment; old snapshots remain unchanged. This evidence comparison is separate from the framework's admitted/scored inputs and does not manufacture a confidence score.

## Primary event assessment

For supported transaction claims, components are interpreted before assessment inputs are prepared. The primary `assessment` now contains the component outcome and evidence gaps. The separate `credibility_assessment` retains authority, temporal admission, provenance and independence checks; it is not used as a conflicting primary outcome. Saved lists and the result view use the same primary conclusion. Earlier snapshots are not migrated: run again to create a result with this assessment basis.

Active/passive approval wording and authorised/authorized forms are supported. Completed approval requires an affirmative status or explicit completed-approval assertion. Populated references, waiting states, negations, conflicting fields and qualified approvals are not accepted as proof of completion. Language interpretation is still bounded, not a general semantic model.

## Coherent-flow repair and acceptance checks

The approval-event and operational-practice checks now share completion-state interpretation. A populated approval date or reference is not enough: pending, qualified and inconsistent approval assertions remain unresolved or conflicting. A separate statement that approval was not logged in CRM does not negate an explicit completed approval. Practice comparisons still require the claimed role, threshold, scope, event and timing.

Approval-event modifiers can appear in different supported positions: active/passive approval or authorisation, a supplied record identifier, a reported channel and before-signing timing. Every asserted component is retained. Without an identifier, a unique actor-and-amount candidate is disclosed; multiple candidates are shown for clarification and never combined into one transaction. This is bounded interpretation, not unrestricted natural-language understanding.

Explicit links to the same record can connect an approval date with a signing date in another passage. Multiple dates remain unresolved rather than choosing a convenient pair. Missing dates, same-day dates, different records and CRM close dates cannot prove approval-before-signing. Component evidence is included in the review inputs even when the initial ranking omitted it. More than 50 contributing passages prevents a fully supported result and requires further review.

The main assessment, list, export and reopened snapshot share the saved primary conclusion. The separate credibility assessment retains source, authority and independence limitations. Unsupported event wording produces **Not assessed automatically**: this means interpretation is incomplete, not that the claim is false or evidence is absent. Policy adoption checks are displayed for formal-rule claims, not as the explanation for an event comparison.

For a local showcase, use **Run again** to create new snapshots. Historical results deliberately retain their original assessment. With the supplied corpus and an assessment date of **2026-02-10**, check:

| Claim | Expected recorded-evidence result |
| --- | --- |
| Diane approved 25% discount on Slack | Supported by the available record; unique candidate DEAL-041, original Slack message unverified |
| For DEAL-041, the 25% discount was approved by Diane on Slack | Same recorded-evidence result |
| Diane authorised a 25% discount for DEAL-041 before signing | Partially supported; signing order not established |
| DEAL-014 Diane approved 18% discount on Slack | Supported by the available record; missing CRM logging is a separate documentation issue |
| DEAL-041 Diane approved 24% discount on Slack | Contradicted by the available record's discount field |
| DEAL-999999 Diane approved 25% discount on Slack | Not established; no matching transaction |
| DEAL-041 Diane approved 25% discount and the customer paid in full | Not assessed automatically; the entire compound claim is not supported by the interpreter |

These are regression examples, not a fixed answer table or an independent client validation set. Tests also substitute unrelated identifiers, names, amounts and channels. Verify browser interaction before presenting: save, inspect exact citations and graph, reopen from history, export, and save a review revision. No paid model is required. Broader interview interpretation, arbitrary compound assertions, source authentication and general language reliability remain outside this repair.
