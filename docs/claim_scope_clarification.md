# Optional scope clarification in the corpus screen

The existing `/api/corpus/search` response now includes `scope_context`. Its first
bounded intake rule detects discount-approval claims with no explicit deal scope
when two distinct policy documents contain new-business and renewal requirements.
The supporting original passages are returned so the user can inspect why the
question is offered. This establishes a meaningful scope distinction, not the
current applicability of either policy.

The existing claim screen offers new-business, renewal and all-deal choices plus
a free-text answer. The user can continue without narrowing. Explicit scopes,
universal claims, specific record IDs and unsupported intents are not interrupted
by this rule. Not asking a question does not certify that a claim is unambiguous.

Answers use the optional `scope_answer` search field. The original claim stays
byte-for-byte unchanged. The answer is appended to the retrieval query and is
recorded separately in the response, with a displayed facet containing the
original claim and `Scope supplied by user: ...`. Search ranking is influenced
by scope; this does not exclude all other scopes or establish applicability.

The existing prepared-assessment form requires that scoped facet when an answer
is selected. It never rewrites supplied judgements to fit a new scope. Changing
scope resets the form and result; changing the claim resets the scope. The
existing assessment and history APIs already preserve the original claim and
facet, so an explicitly submitted scoped facet is retained with its result.

This is the clarification interaction for the current retrieval/prepared-assessment
workflow. It does not turn the screen into an automatic assessment route, infer
authority, approve proposed relationships or fill quality scores. Parsing failures
are not presented as clarification questions. General semantic clarification and
automatic assessment after an answer remain separate unfinished capabilities.
The component uses existing card/button styles; no stylesheet is changed.
