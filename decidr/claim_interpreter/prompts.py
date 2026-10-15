"""Prompt and instruction text constants for claim interpretation.

Pure string literals moved verbatim from the original claim_interpreter module.
"""

_INTERPRETATION_INSTRUCTION = """Interpret the ENTIRE claim into necessary atomic components, not a verdict.
Represent what the user asserts without deciding whether it is true: no evidence is evaluated here.
If the user explicitly asserts that a stored value is accurate, preserve that accuracy assertion as
value_accuracy; do not confuse extracting that assertion with proving it. Do not ADD accuracy when
the user merely says a value was recorded. 'Within N units of time' is an upper-bound (lte) assertion.
Use arbitrary domains and wording, including passive voice and negation. Preserve every material
conjunct, entity, numeric quantity/unit/comparator, scope, time and modality. claim_quote must be an
EXACT non-empty substring of original_claim. Component text may explain that span but cannot add facts.
Use numeric quantity values; convert written numerals to digits, preserving their unit. gt is strictly above; gte includes
the boundary. A scalar threshold value stated as 'the threshold is N' has comparator eq;
do not invent an inclusive/exclusive approval range unless the claim expressly states it.
Keep necessary scope and start-point conditions. Don't interpret a recorded value as
accurate, a report as an event, approval action as authority, proposed change as adopted, a review date
as expiry, or current state as historical. Select the target that answers the user's actual assertion. Target and time are separate dimensions:
formal_requirement means the content of a documented rule, obligation, deadline or threshold;
formal_authority means the documented right/role to approve, delegate or decide. A claim identifying
a formal approver or authorised decision-maker concerns formal_authority; a qualifying threshold does not turn a
claim about WHO holds the right into a claim about WHAT a policy requires. Use formal_authority then.
Both normative targets may
be current OR historical; preserve that time in temporal rather than reclassifying them as observed
practice. The word 'current' alone never decides the target. event asserts a particular occurrence;
observed_practice asserts how actions are actually performed; reported_statement asserts what was
said or recorded; value_accuracy asserts whether a stored value is correct; current_state and
historical_state describe actual operational conditions at present or in the past, not a rule's text.
A generic statement assigning decision responsibility to a role may describe formal_authority even
without the word 'formal'. Present-tense verbs alone do not establish observed_practice. If both a
role assignment and actual practice are plausible, retain that target ambiguity explicitly; a formal
role reading can be the assessed facet but is not proof of actual compliance. Consultation does not
assert agreement, successful completion, or an exception-free process; never add those assertions.
Keep conditional permissions/obligations as one proposition with their conditions attached. 'If P,
X is permitted provided Q' does not separately assert P happens or that X is unconditionally permitted.
Keep universally quantified statements (all/every/each) as one verbatim proposition, including all
conjuncts, shared scope and timing. A statement that actions receive approval asserts actual behavior;
do not replace it with being subject to an approval requirement or process.
Otherwise split independent conjuncts into separate components; a before/after timing assertion is its own
component. Shared entities may be repeated. If material wording is ambiguous, preserve alternative
meanings in ambiguities, never silently choose.
Ambiguities must be competing plausible readings or material missing meaning, not explanations of
normalization: an unambiguous word such as 'above' mapping to gt is not an ambiguity. Evidence gaps
also do not make claim wording ambiguous. Preserve actual missing currency, scope or referent details.
Explicit current/past/date qualifiers must be preserved in temporal for the components they constrain.
temporal and modality are plain strings describing
what was said (use '' only if unstated). search_queries are short varied retrieval phrases derived from
this claim, with exact record identifiers preserved. Do not invent names, document IDs or answers.
"""


_VERIFICATION_INSTRUCTION = """Independently verify the proposed interpretation against the ORIGINAL claim.
This stage checks asserted meaning, not truth or evidential support. If the original claim explicitly
says a stored value is accurate, value_accuracy is the correct target even though accuracy has not
yet been established. Reject an added accuracy assertion only when the original merely reports a
stored value. Preserve ordinary bounds: 'within N units of time' means lte, not exact duration eq.
Check EVERY component and every original clause. Assess each structured component JOINTLY across
text, entities, predicate, polarity, quantities, scope, temporal and modality. A qualifier need not be
repeated in text if it is faithfully represented in its dedicated field. In particular, 'current' in
temporal preserves a current-time assertion even if the component text summarizes only the predicate.
Exact quotes alone do not establish semantic fidelity; check the meaning represented by the fields.
Check the TARGET against the semantic object: a current or past formal obligation/threshold remains
formal_requirement, and a documented approval/delegation right remains formal_authority. Assertions
identifying a formal approver or authorised decision-maker concern formal_authority,
even if they include a threshold qualifier. Do not replace WHO holds a right with WHAT is required.
Current and historical timing belongs in temporal; current_state/historical_state are actual operational states.
Do not reclassify a normative rule as observed practice just because it says current or past.
Reject invented scope/entities, missing conjuncts, polarity changes, quantity/unit/boundary changes,
missing timing, lost exceptions, changing requirement into practice, approval action into authority,
recorded value into value accuracy, reported statement into actual occurrence, proposed into adopted,
or current into historical state. A scalar 'threshold is N' asserts equality of a threshold value,
not a particular inclusive or exclusive range: reject invented gt/gte/lt/lte there. Quantities may
normalize number words but cannot change values.
Return component_checks as an object keyed by each and only each exact component ID, with valid and
reason for every key. Set that check's valid=false
only for a real error in that component. For a material assertion missing from all current components,
add omitted_claim_spans with an EXACT original-claim substring and the missing meaning. Otherwise use [].
Uncertainty explicitly retained in ambiguities is allowed; it must not be asserted as resolved.
Check ambiguity entries too: they need competing plausible readings or material missing meaning.
Mark the relevant component check invalid if an ordinary unambiguous comparator normalization is
mislabelled ambiguity; explanatory notes and evidence gaps are not ambiguous claim meanings.
Do not discard genuine unresolved currency, scope or referent details.
Generic role responsibility may be formal_authority even without the word formal. A present-tense
verb alone does not settle formal assignment versus actual practice; retain that ambiguity when material.
Consultation does not promise agreement or successful completion. Reject those added implications.
Conditions of a permission or obligation must remain attached to its proposition, not be split into
assertions that the condition occurs and the permission is unconditional.
Universal statements must preserve all conjuncts under the same quantifier, scope and timing.
Receiving approval is an action; being subject to a rule does not preserve that asserted action.
The assessment joins components as logical AND. Component-ID references in scope do not encode
implication. Reject a separately asserted premise or condition even if another component refers to it.
Judge only the CURRENT proposed interpretation against the original claim. No earlier candidate
or generation-repair feedback is part of this independent audit; do not speculate about prior defects.
There is no global verdict or issues field. Put positive explanations in the relevant check's reason.
Do not create an omission entry to say that nothing is missing; omission entries identify actual gaps.
"""


_TARGET_VERIFIER_STANDARDS = {
    "formal_requirement": """Assess rule content, not transaction compliance. Preserve scope, conditions,
exceptions and adoption; drafts/proposals are not adopted. Preserve strict/inclusive bounds.
General requirements can entail narrower trigger ranges, but scalar cutoffs must match:
'the threshold is N and above' is not supported by a different N through range overlap.
Review dates are not expiry. Actions or ownership alone establish no rule.""",
    "formal_authority": """Assess the documented right to perform the claimed decision, at the relevant date
and scope. Distinguish policy-adoption rights from individual transaction approval rights, document
ownership, role title, participation and performed actions. None alone supplies a missing authority
grant. Preserve delegation conditions, effective periods and revocations; proposals are not grants.
Assigned decisions are not necessarily final/sole; missing tie-break rights do not refute consultation.""",
    "event": """Assess whether the specific event occurred, with matching record, actor, value and timing.
Missing, pending, awaiting or not-approved records and approval references do not establish completed
approval. Same-day dates alone cannot prove before/after order. A policy requirement does not prove
compliance. A record proves only its stated event, not unstated authority or independent accuracy.
Preserve the claimed approval kind: a pilot, informal permission or trial is not formal adoption.
Generic 'signed off' does not establish a specifically formal approval when its kind is unstated;
retain that limitation rather than filling it from another passage. An explicit rejection of formal
approval can contradict that event even if a pilot was permitted.""",
    "observed_practice": """Assess what actually happens in the relevant operations, distinct from the formal
procedure. Specific completed records and reports may establish observed examples, not universal
practice without representative coverage. Preserve exceptions and conflicting observations; do not
infer completion from pending items or policy instructions. Separate reported practice from direct observation.
An agreed workaround or instruction is not proof that anyone followed it. Uncertainty about whether
an action happened does not contradict a claim that it happened. Ground counterexamples in actual
observations within the claimed scope. 'Afterwards' needs its stated reference event; do not invent
an unstated closing, signing or release milestone.""",
    "reported_statement": """Assess what the identified speaker or source said, with attribution, date and
scope preserved. A statement may support a reported-statement claim without independently proving
that the events occurred. Do not silently convert testimony into observed fact or reverse this distinction.""",
    "value_accuracy": """Evaluate fields for expected_relationship; valid does not mean the claim is true.
ONLY supports requires an actual independent check of the value against separate evidence and its
result. A stored value or audit/review/approval label alone is not proof of accuracy; the model's
independent_validation label is not proof either. An approval-only event can be valid context.
A reported explicit correction can validly contradict accuracy even if the
replacement value is not independently proven. It needs no independent_validation basis.
Uncertainty-only warnings qualify instead.
Use ONLY this selected passage's text: blank notes remain blank; a linked record's correction cannot
be attributed to this passage. Shared identifiers permit finding another record, not copying its facts.
Neither contradiction nor qualification establishes a replacement value.""",
    "current_state": """Assess the actual state as of the assessment date. An earlier completed enduring
transition can inform a later state, with continuity/age limits and no contrary later evidence;
a decision or planned migration does not prove completion or perpetual continuation. A stale
procedure cannot borrow another passage's migration to become counterevidence. A scheduled review
is not expiry. Consider later completion and corrections without importing future events.""",
    "historical_state": """Assess the actual state during the claim's historical period. Preserve the date
and scope; later current conditions do not silently replace the historical state. Distinguish records
of completed actions from policy intentions and proposals. Later recollections require explicit
historical linkage and limitations; preserve relevant changes and conflicting historical evidence.""",
}


_EVALUATION_INSTRUCTION = """Evaluate selected evidence AGAINST EACH NECESSARY CLAIM COMPONENT.
Source metadata is in sources_by_id, keyed by each passage's source_id, exactly once per source.
All source headers and dates still apply to every passage of that source. Select the exact component_id
and evidence_id from the provided data and schema; never invent identifiers. The server supplies each
selected passage's original text and source as its exact citation. Do not output quotations or source_id.
Assess the FULL selected passage including its conditions, exceptions and negation. Assess arbitrary
natural-language assertions, not just approval rules. Include relevant support, contradictions,
qualifications, and material context. Exclude purely unrelated passages. Relationship supports means
the quotation establishes the specific component; similarity, linked IDs and repeated statements do
not establish it. Scope and time fit must be justified, unknown if not established. Source metadata,
headings and neighbouring passages may give context, but each finding must select an actual passage.
time_fit means applicability to evaluating the target period, including counterevidence; it does not
mean equal dates or agreement with the claim. Earlier completed enduring state changes may inform a
later state with continuity/age limitations and no contrary later evidence. A decision or intended
migration is not completion, nor does completion guarantee perpetual continuation. A historical
procedure cannot borrow another passage's migration to become a contradiction itself.
Relationship contradicts asserts incompatible facts. Relationship qualifies adds a condition,
limitation or uncertainty; it does NOT assert that the claim is false. Relationship context is relevant
background that does not establish or refute this component. Relationship unresolved means the
passage cannot settle the relationship. Do not mistake a qualification for a contradiction. An explicit permitted exception contradicts
an absolute claim denying every exception. Do not turn an assertion of consultation into a promise
of agreement, successful completion or a universally compliant process.
Assigned decisions are not necessarily final/sole; missing tie-break rights do not refute consultation.
Missing or undocumented records do not prove that actions, rights or exceptions do or do not exist.
A section heading alone establishes no substantive rule or exception. A record-status statement
without the claimed substantive assertion is context, not support or contradiction of that assertion.
Preserve exact numerical boundaries (> is not >=), quantities and units, explicit negation and scalar
threshold identity: a claim that the threshold is N asserts that cutoff even if followed
by 'and above'. A different cutoff does not support it through range overlap. Distinguish a general
requirement for a narrower range, which can be entailed by a broader requirement.
Preserve pending versus completed, and proposed versus adopted changes. Same-day dates cannot prove temporal order
without time precision. Approval references or awaiting sign-off are not completed approval.
Preserve approval kind: permission for an informal pilot does not establish a specifically claimed
formal adoption. Unqualified 'signed off' leaves the formal-versus-pilot distinction unresolved.
Uncertainty or lack of knowledge is not proof an event did not happen. An agreed instruction is not
proof it was carried out; 'afterwards' refers only to its stated antecedent, not an unstated milestone.
For formal requirements a policy documents a requirement; don't demand proof of every transaction.
For formal authority distinguish the documented role from ownership or performed action. For current
state evaluate completed migration and dated current evidence against stale procedures; a scheduled
review is not policy expiry. For value accuracy, recording the value or approving a record cannot
verify accuracy: only genuine independent validation can be supports with basis independent_validation.
A review or approval event alone verifies that a review or approval occurred, not the accuracy of each
stored value. Independent validation must document an actual check of the claimed value against a
separate evidential basis, with its result; an audit label alone does not provide that check.
A source's own warning about incorrect data qualifies or contradicts accuracy, never verifies it.
For value accuracy, an explicit correction identifying the claimed recorded value as wrong can
contradict accuracy without independently proving the replacement value. An uncertainty-only warning
qualifies instead. Preserve this distinction without assuming a proposed replacement is correct.
For reported statements evaluate what the speaker said separately from whether the events occurred.
Separate customer/employee scope, policy/practice and target dates. Never infer independent
corroboration from passage count, copying or circular references. Basis describes what the passage
establishes: direct_statement, recorded_action, reported_statement, independent_validation, contextual.
For normative targets, a decision record explicitly stating an adopted rule/grant is direct_statement
about that norm. A vote or transaction approval occurrence alone is recorded_action, establishing only
the action. Meeting source type alone proves neither normative content nor adoption authority.
Informal noncompliance or stale reported instructions may remain context rather than contradicting
the applicable formal norm; assess adoption and temporal applicability before asserting a norm change.
Pending/not-approved/reference-only records cannot establish a completed event. Same-day
approval/signing with no timestamps cannot establish before/after. All support still needs a selected
original passage. A specialised failure to parse does not refute broader semantic evidence.
Return unresolved_questions for uncovered material components and remaining uncertainty. Findings
must be component-specific and reasons must explain the actual source content, not generic assurances.
Use at most two findings per component/passage pair, allowing distinct support and contradiction.
Keep additional qualifications in limitations; if that cannot faithfully represent the passage,
return unresolved with an explanation. Do not silently drop material conditions or counterevidence.
"""
