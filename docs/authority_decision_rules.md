# Authority decision rules and current implementation

Authority is specific to the assertion being assessed. The following is the
review contract; it is not a claim that automatic authority resolution is complete.

| Target | Relevant basis | Insufficient by itself |
| --- | --- | --- |
| Formal rule | Documented adoption or delegation for this rule, matching business scope and effective period | Ownership, a title, a reference, or a bare approved label |
| Recorded statement | A traceable record identifying the speaker and preserving what was said in context | The speaker's power to make policy; that is a different question |
| Underlying event | Evidence of the actual event, attributable to a suitable witness or recording system, with matching scope and time | An instruction to act, hearsay or a policy requirement |

For a formal authority finding, reviewers must distinguish the policy owner,
the person or body adopting the rule, and the operational approver named by it.
An adoption reference must identify the relevant document/version or decision;
the signatory's rights and applicable conditions need their own evidence.
Unknown dates or unresolved scope must stay unknown. Circular references and
repeated accounts do not create independent authority or corroboration.

## Enforced admission rules

The existing adapter requires supplied scope, time and authority flags to be
true, alongside matching explicit targets and modes. Metadata conflicts,
ineffective dates, unresolved supersession boundaries and ineligible lifecycle
states already prevent admission. These gates remain in place.

Formal inputs now also fail admission when stored own-document approval text
explicitly includes non-approval, even if a caller supplies approved status and
verified authority. The shared clause parser separates referenced-document
wording; the shared negative recogniser handles not approved, not yet approved,
never approved and unapproved. A supplied draft or unapproved key also prevents
formal admission. Contradictory positive and negative approval remains blocked.

This is an exclusion rule, not a positive verifier. It applies to support and
contradiction edges in the formal lane, including legacy unspecified targets.
The source and supplied flags remain visible with the exclusion reason; no
metadata or saved result is rewritten. A historical non-approval statement with
unresolved temporal qualification must be resolved before formal admission.

The same policy-adoption exclusion does not apply to observed statements/events:
an unapproved document can still record a statement. Existing target, scope,
time, authority, provenance and scoring checks still apply. Admission is not a
guarantee that the evidence reaches the configured materiality threshold.

## Remaining work

The proposal API still leaves authority unverified. Cited authority context and
explicit references aid review but do not resolve adoption rights or delegation.
The supplied-assessment endpoint continues to accept positive reviewer/caller
judgements conditionally; it does not independently authenticate that review.
Automatic authority verification requires evaluated extraction and comparison of
the relevant rights, actions, scope and dates. No new weights or frontend changes
are introduced by these rules. Existing immutable history remains unchanged.
