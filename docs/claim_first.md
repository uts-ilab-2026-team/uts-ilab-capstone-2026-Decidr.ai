# Current employee claim assessment

Run `uv run streamlit run app/Home.py` after configuring and ingesting the local Phase 2
corpus. **Assess a Claim** accepts a declarative statement through the conversation input.
Bounded intake retains the original wording, values, negation, scope and dates. Unresolved
meaning requests clarification; it is not an evidence verdict.

A resolved submission retrieves evidence and receives an **automatic assessment before
optional human review**. No local LLM is needed. Production uses `bounded-evidence-5` and
the shared deterministic reasoner. The structured-extraction candidate is an isolated,
unpromoted experiment; it has no production configuration switch or employee-route import.

Source registration now uses [document-scoped metadata](source_metadata_correction.md): own
approval is separated from referenced drafts, superseded dates retain an unresolved boundary,
and update dates are not creation dates. Existing saved assessments and the working ledger
have not been rewritten. The corrected research dataset and reviewer packet are separate;
their adjudication is not a condition for receiving an automatic employee assessment.

The response shows the claim answer/verdict, supporting sources, contradicting sources,
exceptions/practice differences, genuine evidence gaps, cited next actions and an expandable
graph. Exact passages and source links remain available. Classification failures are present
but unresolved evidence; retrieval limits describe the search; neither is a fabricated gap.
The four reasoner outcomes retain their meaning. Cross-target findings and incomplete
coverage are shown separately, not introduced as new coverage verdicts.

Current retrieval uses lexical ranking with a 50-candidate budget followed by explicit
source-provenance expansion under the same 50-candidate cap. When lexical retrieval fills
that budget, expansion cannot add candidates. The experiment reports that behaviour and
compares smaller-budget expansion with equal-budget lexical retrieval. Similarity or graph
proximity never establishes a relationship, authority or source independence.

The claim register and conversations retain immutable assessment history. Older results
keep their original verdict; automatic reassessment of a frozen packet creates a new run.
Human confirmation/correction is optional and follows the automatic result. A named review
records its rationale, before/after judgement and parent snapshot, without turning it into
an independent study reference. Reviewer names are audit labels, not authentication.

Frozen source links include assessment, source and evidence identity. Graph filters disclose
shown/total findings, filtered candidates and omissions due to bounds. All evidence remains
inspectable outside the bounded graph and in exports. HTML and JSON exports consume the
same saved snapshot; sensitivity is a temporary comparison, never a history edit.

**Evidence Explorer** supports source inspection without creating a claim. **Knowledge
Risks** summarises evidence-linked findings from registered claims; it is not an audit of
all transactions. Research/admin pages, blind review and adjudication are separate from
employee review. Do not use held-out or submitted study claims as development examples.

Current classifier and snapshot details: [automatic assessment](automatic_claim_assessment.md).
Routing and follow-up history: [conversation implementation record](conversational_assessment.md).
Measured limitations: [known limitations](known_limitations.md).
The [superseded human-first instructions](archive/pre-structured-extraction/docs/claim_first.md)
are retained byte-for-byte as history, not current instructions.
