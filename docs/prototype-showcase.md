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
