# Cited authority context

## Cross-document references

Proposals also return `authority_links`. This searches original indexed passages
for an exact, unique leading document code within the same release. It retains
the full referring passage, including negative wording, as an exact citation.
Same-source references and excluded/failed sources are omitted. Ambiguous codes
remain unresolved. Results use stable ordering, a 12-passage display cap per
target source, and explicit total/omitted counts. This cap is separate from the
retrieval candidate budget: linked passages do not become assessment inputs.

Each reference includes source metadata and whether its recorded creation date
is after the assessment date, on/before it, or missing. This is not an event-date
or applicability determination. Later records remain visible with that warning.
Metadata conflicts are retained for inspection.

A reference, even one saying "approved", does not verify the signatory's rights,
decision scope, historical role or policy adoption. Those checks remain
unresolved. References can guide the next review step without contributing votes,
scores or graph edges. They are returned by the proposal API; the current
frontend and supplied-assessment history do not consume this additional field.

Interpretation proposals include an `authority_context` object bound to the
requested facet, assessment date, source and focal evidence. This is an
inspection aid, not an authority verifier or an additional assessment.

It separates three assertions:

- Document owner: the person or role named in an exact opening-header quotation.
- Document approval: the own-document approval clauses grounded in that header,
  using the shared approval parser, including negative approval wording.
- Operational approver: the role and conditions extracted from the focal
  quotation by the existing complete approval-rule grammar for policies and
  procedures.

Header keys and values must match their quoted text. Quotes must resolve to
original same-source evidence, with exact source, locator and character offsets.
Missing header evidence, malformed clause offsets and unresolved approval
metadata remain unresolved. Legacy metadata alone cannot establish a finding.

`document_approval.value` uses the existing lifecycle vocabulary (`current`,
`draft`, `superseded`, `withdrawn`, `unknown`). In particular, `draft` here includes
negative approval statements; it is not proof of the document's drafting stage.
The raw approval quotation remains available. A documented assertion reports
what the source says, not independently verified authorisation.

An operational approver is not necessarily the document owner or the person
authorised to adopt the policy. The extracted rule describes the evidence;
the interpretation proposal separately compares it with the requested facet.
The context's date records the requested assessment date, not a finding that
the cited roles or rules were valid on that date.

## Boundaries

`authority_verified` stays null and `review_required` stays true. Policy adoption,
cross-document sign-off, role occupancy, delegation and decision-rights resolution
are not implemented by this component. Source authenticity, independence and
temporal applicability are not established by these citations.

This change does not populate credibility scores, admit graph edges, change
verdicts or alter the frontend. Header citations are context, not additional
independent votes. Existing assessment requests remain unchanged. The supplied
assessment history does not yet persist this context as a separate authority
record; it continues to save its existing request and evidence snapshot.

Tests exercise distinct owner and approver roles, exact quotations, missing
proof, negative and referenced approval wording, metadata conflicts, invalid
offsets and the HTTP proposal-to-assessment boundary.
