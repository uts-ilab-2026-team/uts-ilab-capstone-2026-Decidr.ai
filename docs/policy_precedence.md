# Policy precedence for formal corpus assessments

For an explicit `formal_rule` assessment, applicable approved policy evidence
takes precedence over a contrary role description or decision-rights summary
for the same supplied facet. For example, an inclusive policy boundary must not
be silently replaced by an exclusive boundary in a summary. This mechanism
does not itself parse boundaries or assign support/contradiction relationships.

In particular, "above 15% requires approval" does not itself assert that exactly
15% needs no approval. That narrower statement may be incomplete rather than
contradictory. Preserve such a boundary difference as qualification/context
unless the evidence explicitly establishes an incompatible requirement. The
policy's inclusive wording establishes the 15% case directly.

The policy must first pass the existing citation, target, scope, date, authority,
lifecycle and metadata gates. It must have stored source type `policy`, supplied
class `approved_policy`, supplied approval key `approved`, positive own-document
approval metadata and a documented effective start date. Its evidence must reach
the configured materiality threshold when assessed without the summaries.

If eligible policies disagree on the facet, precedence does not resolve their
conflict. Otherwise, conflicting formal inputs with stored type
`organisational_information` and supplied class `role_description` or
`decision_table` are retained in the response with exact citations, original
relationships and an explicit precedence reason. They do not create decisive
edges. The assessment reports the documentation inconsistency in its qualifiers,
summary and `CORPUS_POLICY_PRECEDENCE_V1` rule trace.

This narrow precedence rule does not override another policy, procedure,
amendment, exception or observed practice. Same-stance summaries still use the
existing dependence and corroboration rules. Legacy unspecified targets and
direct graph-framework callers retain their previous behaviour. Existing saved
snapshots are not rewritten; new saved results include the resulting dispositions.

Applicability and relationships remain supplied judgements. The caller must
account for applicable amendments and exceptions when declaring scope and time.
Precedence does not establish that retrieval found every applicable document,
verify authority or establish actual compliance. The frontend appearance and
numeric weights are unchanged.
