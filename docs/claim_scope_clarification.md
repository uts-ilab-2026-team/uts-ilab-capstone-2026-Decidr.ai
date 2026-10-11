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

## General bounded scope resolution

The same optional card now covers five supported distinctions:

| Claim with missing scope | Question | Corpus grounding |
| --- | --- | --- |
| Discounts require approval | New business, renewal or all deals | Two distinct policies' formal requirements |
| Onboarding takes six weeks | Customer implementation or new hires | Two distinct onboarding policies |
| Finance must approve this expense | Expense amount | Both approval amount bands in the expense policy |
| Sales owns renewals | Commercial negotiation, relationship health or final accountability | Renewal procedure responsibilities and steps |
| Engineering approves product requests | Prioritisation, feasibility or P1 sprint entry | Product process responsibilities and approval requirements |

Rules match supported wording and exact document passages, never source IDs,
reference labels, retrieval scores or expected verdicts. Every required grounding
passage must be present in an ingested policy or procedure in an allowed section.
The question does not establish approval, applicability or current authority.
Unknown wording continues without clarification; it is not evidence of clarity.

Explicit universal assertions and record IDs are not narrowed. Explicit scope,
amount or decision stage suppresses the corresponding question. Original claim
text remains unchanged. Answers are user-supplied scope, not validated facts or
credibility judgements. A single optional question is returned per request.

This is bounded scope resolution, not general natural-language interpretation.
It does not resolve conflicting onboarding clock origins, infer dates, establish
renewal decision authority, or convert practice into policy. Invoice prerequisites,
export conditions and documented exceptions belong in the assessment when the
assertion is already clear. No automatic verdict, authority verification, event
verification or repeated clarification dialogue is introduced.
