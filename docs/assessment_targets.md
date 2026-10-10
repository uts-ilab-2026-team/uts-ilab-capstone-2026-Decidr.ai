# Supplied assessment targets

The supplied-assessment adapter and HTTP route distinguish:

| Value | Assertion being assessed |
| --- | --- |
| `recorded_statement` | What a source records somebody saying, reporting or instructing |
| `underlying_event` | Whether the described action, event or state actually occurred |
| `formal_rule` | What an applicable prescribed rule requires or permits |
| `unspecified` | Legacy request without this distinction |

The request declares `assessment_target`. Each input declares `evidence_target`
and a nonblank `target_basis` when its target is explicit. These are supplied
interpretations of the evidence's bearing on this facet, not source-type labels.
An interview is not automatically restricted to one target, and a message does
not automatically establish an event. One passage can be compared with different
claims in separate assessments, with separately justified declarations.

For explicit targets, the adapter admits decisive edges only when the declarations
match and the mode is appropriate: observed for statements/events, formal for
rules. Missing or mismatched declarations retain the input, quotation and reasons
without creating a decisive edge. The existing stance, scope, time, authority and
provenance checks still apply. Qualifiers remain non-decisive.

Matching declarations are not semantic verification. The caller can supply an
incorrect target or rationale. This contract does not parse a claim, establish
entailment, verify reported events or authenticate an interpretation as reviewed.
The authority multiplier, numeric weights and independence rules are unchanged.
No alternative scoring experiment is enabled by selecting a target.

Responses retain the `assessment_target` on the facet result and each input's
target and basis in `supplied_judgements`. `target_validation` identifies whether
supplied declarations were checked or the legacy path was used. The nested core
framework assessment retains its existing schema; consume it with the enclosing
facet target and original claim. Direct graph-framework callers are unchanged.

When both targets are unspecified, old admission behaviour is preserved and the
response explicitly says no statement/event/rule check was performed. Supplying
only one side is insufficient for admission. This compatibility path must not be
presented as verified event assessment or used to opt into experimental scoring.
Saved inputs and earlier snapshots are not rewritten. The additive response fields
keep schema version v1; clients must retain them when exporting targeted results.

The next scoring experiment may use this contract, but target labels alone will
not validate a new formula or justify promoting it. Independent review of the
interpretations and evaluation beyond the provisional development cases remain
separate work.
